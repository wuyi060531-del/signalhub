import os
from decimal import Decimal
from datetime import datetime, timezone
from ..pipeline import execute, dump
from .providers import MockProvider, CompatibleProvider, messages, cache_key

class AIService:
    def __init__(self, engine, provider=None):
        self.engine, self.provider = engine, provider

    def enrich(self, item_id):
        mode = os.getenv('AI_PROVIDER','disabled')
        if mode == 'disabled' and self.provider is None: return {'state':'disabled','message':'AI 关闭；规则提取和匹配仍可运行'}
        if self.provider is None and mode not in ('mock','compatible'):
            return {'state':'blocked','message':'未知 AI Provider 配置'}
        # 会话锁跨越网络请求，防止同一信息并发调用两次；连接关闭也会释放锁。
        with self.engine.connect() as lease:
            key=f'ai:item:{item_id}'
            acquired=execute(lease,'SELECT pg_try_advisory_lock(hashtext(:key))',key=key).scalar_one()
            lease.commit()
            if not acquired: return {'state':'blocked','message':'该信息的 AI 任务正在执行'}
            try: return self._enrich_locked(item_id,mode)
            finally:
                execute(lease,'SELECT pg_advisory_unlock(hashtext(:key))',key=key)
                lease.commit()

    def _enrich_locked(self, item_id, mode):
        provider = self.provider or (MockProvider() if mode=='mock' else CompatibleProvider())
        try:
            provider_key = cache_key(provider)
        except ValueError:
            return {'state':'blocked','message':'AI 服务地址配置无效'}
        with self.engine.connect() as conn:
            item = execute(conn,'SELECT payload,content_hash FROM items WHERE id=:id',id=item_id).mappings().one()
            profile_row = execute(conn,'SELECT settings,updated_at FROM user_profiles WHERE id=1').mappings().one()
            profile, profile_revision = profile_row['settings'], profile_row['updated_at']
            cached = execute(conn,'SELECT 1 FROM ai_enrichments WHERE item_id=:id AND content_hash=:hash AND provider=:provider AND profile_updated_at=:revision',id=item_id,hash=item['content_hash'],provider=provider_key,revision=profile_revision).first()
            if cached: return {'state':'cached'}
        body = item['payload']['body']
        usage_id = None
        input_price = output_price = Decimal(0)
        if provider.name != 'mock':
            if os.getenv('AI_PAID_AUTHORIZED') != 'true' or not os.getenv('AI_API_KEY') or not os.getenv('AI_MODEL'):
                return {'state':'blocked','message':'真实模型需要明确授权、密钥和模型配置'}
            if len(body.encode())>60000: return {'state':'blocked','message':'原文超过模型输入上限'}
            try:
                input_price = Decimal(os.getenv('AI_INPUT_USD_PER_MILLION','0'))
                output_price = Decimal(os.getenv('AI_OUTPUT_USD_PER_MILLION','0'))
                budget = Decimal(os.getenv('AI_MONTHLY_BUDGET_USD','0'))
                max_calls = int(os.getenv('AI_MAX_CALLS_PER_MONTH','0'))
                if not all(x.is_finite() for x in (input_price,output_price,budget)) or budget<0 or max_calls<0:
                    raise ValueError('预算无效')
            except (ValueError, ArithmeticError):
                return {'state':'blocked','message':'价格或预算配置无效'}
            if input_price<=0 or output_price<=0: return {'state':'blocked','message':'需配置真实价格才能计算预算'}
            input_bytes=sum(len(message['content'].encode()) for message in messages(body,profile))+1024
            reserve = (Decimal(input_bytes)*input_price+Decimal(1024)*output_price)/Decimal(1000000)
            month = datetime.now(timezone.utc).strftime('%Y-%m')
            with self.engine.begin() as conn:
                execute(conn,'SELECT pg_advisory_xact_lock(754301)')
                current = execute(conn,'SELECT count(*) AS calls,coalesce(sum(coalesce(actual_usd,reserved_usd)),0) AS cost FROM ai_usage WHERE month=:month AND provider<>\'mock\'',month=month).mappings().one()
                if current['calls']>=max_calls or current['cost']+reserve>budget:
                    return {'state':'blocked','message':'月度调用/费用上限已阻止请求'}
                usage_id = execute(conn,"INSERT INTO ai_usage(month,provider,state,reserved_usd) VALUES (:month,:provider,'reserved',:reserve) RETURNING id",month=month,provider=provider.name,reserve=reserve).scalar_one()
        try:
            result,input_tokens,output_tokens = provider.analyze(body,profile)
            if type(input_tokens) is not int or type(output_tokens) is not int or input_tokens<0 or output_tokens<0:
                raise ValueError('模型用量格式无效')
            result.verify(body)
            with self.engine.begin() as conn:
                execute(conn,'''INSERT INTO ai_enrichments(item_id,content_hash,provider,result,profile_updated_at) VALUES (:id,:hash,:provider,CAST(:result AS jsonb),:revision) ON CONFLICT DO NOTHING''',id=item_id,hash=item['content_hash'],provider=provider_key,result=dump(result.model_dump()),revision=profile_revision)
                if usage_id:
                    cost = (Decimal(input_tokens)*input_price+Decimal(output_tokens)*output_price)/Decimal(1000000)
                    execute(conn,"UPDATE ai_usage SET state='success',actual_usd=:cost,input_tokens=:input,output_tokens=:output WHERE id=:id",id=usage_id,cost=cost,input=input_tokens,output=output_tokens)
            return {'state':'success','provider':provider.name,'result':result.model_dump(),'input_tokens':input_tokens,'output_tokens':output_tokens}
        except Exception as exc:
            if usage_id:
                with self.engine.begin() as conn:
                    # 失败仍保留预留金额：服务端可能已收费，不能按零元处理。
                    execute(conn,"UPDATE ai_usage SET state='failed' WHERE id=:id",id=usage_id)
            return {'state':'failed','error':type(exc).__name__,'message':'增强失败，保留原始信息和规则结果'}
