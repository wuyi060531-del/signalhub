package io.signalhub;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import jakarta.validation.constraints.*;
import java.util.*;
@Service
public class TranslationQueue {
    private final NamedParameterJdbcTemplate db;
    public TranslationQueue(NamedParameterJdbcTemplate db) {this.db=db;}
    public record Request(@NotNull @Size(min=1,max=20) List<@NotNull @Positive Long> ids,@Min(1) @Max(2) int depth,boolean retry) {}
    public Map<String,Object> status() {
        var rows=db.queryForList("SELECT available AND updated_at>now()-interval '2 minutes' AS available,provider_revision,message,updated_at FROM translation_runtime WHERE id=1",Map.of());
        return rows.isEmpty()?Map.of("available",false,"message","本地翻译未启用，原文可正常阅读；见双语阅读文档准备本地模型"):rows.getFirst();
    }
    @Transactional
    public Map<String,Object> request(Request request) {
        var runtime=status();
        if(!Boolean.TRUE.equals(runtime.get("available")))return Map.of("state","unavailable","message",runtime.get("message"));
        var rows=db.queryForList("SELECT i.id,i.content_hash FROM items i WHERE i.id IN (:ids) FOR SHARE OF i",Map.of("ids",request.ids()));
        int queued=0;
        for(var item:rows) {
            var p=new HashMap<String,Object>();p.put("id",item.get("id"));p.put("hash",item.get("content_hash"));p.put("revision",runtime.get("provider_revision"));p.put("depth",request.depth());p.put("retry",request.retry());
            queued+=db.update("""
                INSERT INTO reading_translation_jobs(item_id,content_hash,provider_revision,depth) VALUES (:id,:hash,:revision,:depth)
                ON CONFLICT(item_id,content_hash,provider_revision,depth) DO UPDATE SET state='pending',error=NULL,attempts=0,started_at=NULL,finished_at=NULL
                WHERE :retry AND reading_translation_jobs.state IN ('failed','superseded')
                """,p);
        }
        return Map.of("state","accepted","queued",queued,"provider",runtime.get("provider_revision"),"message","本地免费机器参考译文；不发送到外部服务，不参与匹配判断");
    }
}
