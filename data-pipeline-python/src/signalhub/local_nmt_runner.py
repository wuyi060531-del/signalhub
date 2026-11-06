"""Resource-bounded offline runner, executed only by the optional dedicated environment.
Argos en_zh 1.9 / OPUS-MT, CC-BY 4.0. No HTTP, model auto-download or profile input.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

MODEL_SHA256='1a039114d9456b6528fabb65b455b6f156319634a0f984b1f6018f7737d67598'
TERMS=['.NET','Spring Boot','GitHub','Copilot','PyCharm','Flask','Django','Golang','Redis','Elasticsearch','JavaScript','TypeScript','C++','C#','Kubernetes','TensorFlow','PyTorch','Excel','PowerBI','Tableau','PostgreSQL','Python','Java','MySQL','SQL','Spark','Hadoop','Kafka','Airflow','Linux','Docker','RAG','LLM','Git','API','USD','CNY','RMB','EUR','GBP','JPY']


def safe_reference(source, output):
    """Conservative checks, not a proof of semantic correctness; originals remain available."""
    output=output.replace('▁',' ').strip()
    if not re.search(r'[\u3400-\u9fff]',output) or '⁇' in output or '\ufffd' in output:return None
    numbers=re.findall(r'\d+(?:[.,]\d+)*',source)
    if any(n not in output for n in numbers):return None
    source_numbers=set(re.findall(r'\d+',source))
    month_names=['January','February','March','April','May','June','July','August','September','October','November','December']
    for month,name in enumerate(month_names,1):
        if re.search(r'\b'+name+r'\b',source,re.I):source_numbers.add(str(month))
    for number,name in enumerate(['one','two','three','four','five','six','seven','eight','nine','ten'],1):
        if re.search(r'\b'+name+r'\b',source,re.I):source_numbers.add(str(number))
    if any(n not in source_numbers for n in re.findall(r'\d+',output)):return None
    for term in TERMS:
        in_source=bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])',source,re.I))
        in_output=bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])',output,re.I))
        if in_output and not in_source:return None
        if re.search(r'(?<![A-Za-z0-9])'+re.escape(term)+r'(?![A-Za-z0-9])',source,re.I) and term.lower() not in output.lower():return None
    if re.search(r'preferred|advantage|nice to have|a plus',source,re.I) and not re.search(r'\b(?:must|required)\b',source,re.I) and re.search(r'必须|必需',output):return None
    if re.search(r'\b(?:not|without|never)\b|no (?:degree|experience|requirement)',source,re.I) and not re.search(r'不|无|未|免|非',output):return None
    for source_pattern,output_pattern in [(r"bachelor|undergraduate",r"本科|学士"),(r"master|postgraduate",r"硕士"),(r"ph\.?d\.?|doctor",r"博士")]:
        if re.search(output_pattern,output) and not re.search(source_pattern,source,re.I):return None
    for token,required,forbidden in [('bachelor','本科|学士','硕士|博士'),('master','硕士','本科|学士|博士'),('phd','博士','本科|学士|硕士')]:
        if re.search(r'\b'+token+r"(?:'s)?\b",source,re.I) and (not re.search(required,output) or re.search(forbidden,output)) and not re.search(r'\bor\b',source,re.I):return None
    # Reproduced job-reading errors: durations, requirement modality, routing and coder.
    for source_pattern,output_pattern in [
        (r'\bmonths?\b',r'个月|月'),(r'\byears?\b',r'年'),
        (r'\bdays?\b',r'天|日'),(r'\bweeks?\b',r'周|星期'),
        (r'\broutings?\b',r'路由|路线|导航|routing'),
        (r'\bcoder\b',r'程序员|编程|开发者|开发人员|coder'),
        (r'\bundergraduate\b',r'本科|学士'),
        (r'\bpursuing\b',r'在读|攻读|正在学习|就读|pursuing'),
        (r'\bcontainerization\b',r'容器|containerization'),
    ]:
        if re.search(source_pattern,source,re.I) and not re.search(output_pattern,output,re.I):return None
    if re.search(r'\bcoder\b',source,re.I) and '编译' in output:return None
    if re.search(r'\b(?:required|must)\b',source,re.I) and re.search(r'优先|加分|非必需|不要求',output) and not re.search(r'\b(?:not|no)\b',source,re.I):return None
    if re.search(r'\b(?:intern|internship)\b',source,re.I) and not re.search(r'实习|intern',output,re.I):return None
    return output


def main():
    import ctranslate2
    import sentencepiece
    root=Path(sys.argv[1])
    if hashlib.sha256((root/'model/model.bin').read_bytes()).hexdigest()!=MODEL_SHA256:raise ValueError('model_checksum_mismatch')
    request=json.loads(sys.stdin.read(1024*1024))
    values=request['texts']
    if not isinstance(values,list) or len(values)>160 or any(not isinstance(t,str) or len(t)>2000 for t in values):raise ValueError('runner_input_limit')
    sp=sentencepiece.SentencePieceProcessor(model_file=str(root/'sentencepiece.model'))
    translator=ctranslate2.Translator(str(root/'model'),device='cpu',compute_type='int8',inter_threads=1,intra_threads=2)
    tokens=[sp.encode(t,out_type=str) for t in values]
    if any(len(t)>400 for t in tokens):raise ValueError('runner_token_limit')
    outputs=translator.translate_batch(tokens,beam_size=4,max_batch_size=8,max_decoding_length=512)
    translated=[safe_reference(source,sp.decode(out.hypotheses[0])) for source,out in zip(values,outputs)]
    print(json.dumps({'translations':translated},ensure_ascii=False))


if __name__=='__main__':main()
