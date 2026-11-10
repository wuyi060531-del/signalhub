package io.signalhub;
import org.junit.jupiter.api.Test;
import java.util.List;
import static org.assertj.core.api.Assertions.*;
class CityNamesTest {
    @Test void explicitEquivalentsShareOneCanonicalName() {
        for(String value:List.of("重庆","重庆市","Chongqing","chongqing"," CHONGQING ","Chongqing City"))
            assertThat(CityNames.canonical(value)).as(value).isEqualTo("重庆");
        for(String value:List.of("成都","成都市","Chengdu","chengdu"))
            assertThat(CityNames.canonical(value)).as(value).isEqualTo("成都");
        assertThat(CityNames.canonical("Shanghai")).isEqualTo("上海");
    }
    @Test void compoundOrUnknownTextIsNotRecognized() {
        for(String value:List.of("Chongqing, Chengdu","重庆/成都","Chongqing, China","重庆或成都","Chongqing or Chengdu","Remote","Berlin","","  "))
            assertThat(CityNames.canonical(value)).as(value).isNull();
        assertThat(CityNames.canonical(null)).isNull();
    }
    @Test void cityMatchKeepsPlainComparisonForUnlistedCities() {
        assertThat(QualificationRules.cityMatch(List.of("西安"),List.of("西安"))).isTrue();
        assertThat(QualificationRules.cityMatch(List.of("Xi'an"),List.of("xi'an"))).isTrue();
        assertThat(QualificationRules.cityMatch(List.of("西安"),List.of("西安市"))).isFalse();
        assertThat(QualificationRules.cityMatch(List.of("重庆"),List.of("重庆/成都"))).isFalse();
    }
}
