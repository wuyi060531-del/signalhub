package io.signalhub;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;
import java.util.*;
public final class Json {
    // 队列中的日期必须是 ISO 文本，不能使用 Jackson 默认的 [年,月,日] 数组。
    private static final JsonMapper MAPPER = JsonMapper.builder().build();
    private Json() {}
    public static String encode(Object value) {
        try { return MAPPER.writeValueAsString(value); } catch(Exception e) { throw new IllegalArgumentException("JSON 序列化失败",e); }
    }
    public static Map<String,Object> map(Object value) {
        if(value instanceof Map<?,?> m) return (Map<String,Object>)m;
        if(value==null) return new LinkedHashMap<>();
        try { return MAPPER.readValue(value.toString(),new TypeReference<>(){}); } catch(Exception e) { throw new IllegalArgumentException("JSON 解析失败",e); }
    }
    public static List<String> strings(Object value) {
        return value instanceof List<?> l ? l.stream().filter(Objects::nonNull).map(Object::toString).toList() : List.of();
    }
    public static String string(Map<String,Object> map,String key) { Object v=map.get(key); return v==null?null:v.toString(); }
    public static Integer number(Object value) { return value==null?null:((Number)value).intValue(); }
}
