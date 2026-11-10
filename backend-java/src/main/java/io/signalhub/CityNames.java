package io.signalhub;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * 只识别“明确等价”的单一城市名（中文、中文加“市”、英文、英文加 city）。
 * 不识别含逗号、斜杠、“或”等的复合文本，也不由国家、省份或公司推断城市；无法识别时返回 null，调用方保持原有的逐字比较。
 */
final class CityNames {
    private static final Map<String, String> CANONICAL = new HashMap<>();

    static {
        // 与 Python 适配器 CITIES 同一批城市，并补上重庆；键为规范中文名。
        String[][] cities = {{"上海", "shanghai"}, {"北京", "beijing"}, {"深圳", "shenzhen"}, {"广州", "guangzhou"},
            {"杭州", "hangzhou"}, {"成都", "chengdu"}, {"重庆", "chongqing"}, {"南京", "nanjing"}, {"苏州", "suzhou"},
            {"武汉", "wuhan"}, {"天津", "tianjin"}};
        for (String[] city : cities) {
            for (String alias : new String[] {city[0], city[0] + "市", city[1], city[1] + " city"}) {
                CANONICAL.put(alias, city[0]);
            }
        }
    }

    private CityNames() {}

    /** 返回规范中文城市名；不是明确等价写法时返回 null。 */
    static String canonical(String value) {
        if (value == null) {
            return null;
        }
        return CANONICAL.get(value.strip().toLowerCase(Locale.ROOT).replaceAll("\\s+", " "));
    }
}
