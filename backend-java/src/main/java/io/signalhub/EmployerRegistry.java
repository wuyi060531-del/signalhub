package io.signalhub;
import org.springframework.stereotype.Service;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import jakarta.validation.constraints.*;
import java.time.LocalDate;
import java.util.*;

@Service
public class EmployerRegistry {
    static final String JOIN=" LEFT JOIN employer_reviews e ON e.company_key=lower(btrim(i.payload->>'company')) ";
    static final String VERIFIED="e.status='verified'";
    private final NamedParameterJdbcTemplate db;
    public EmployerRegistry(NamedParameterJdbcTemplate db) {this.db=db;}
    public record Review(@NotBlank @Size(max=200) String name,
        @NotNull @Pattern(regexp="china_local|foreign|unclassified") String origin,
        @NotNull @Size(max=10) List<@NotNull @Pattern(regexp="[A-Z]{2}") String> headquartersCountries,
        @NotNull @Pattern(regexp="private|publicly_listed|foundation_owned|central_state|local_state|public_institution|joint_venture|unknown") String ownership,
        @Size(max=200) String industry,@NotNull @Size(min=1,max=10) List<@NotBlank @Size(max=2000) String> evidenceUrls,
        @NotBlank @Size(max=4000) String basis,@NotNull @PastOrPresent LocalDate verifiedOn,
        @NotNull @Pattern(regexp="verified|pending") String status) {}
    @Transactional
    public Map<String,Object> save(Review review) {
        for(String url:review.evidenceUrls()) {
            BusinessService.safeUrl(url);
            if(!url.startsWith("https://"))throw new IllegalArgumentException("核验依据需HTTPS链接，不自动访问");
        }
        if(review.status().equals("verified") && (review.origin().equals("unclassified") || review.ownership().equals("unknown") || review.headquartersCountries().isEmpty()))
            throw new IllegalArgumentException("证据不完整需保持待分类，不能标为已核验");
        db.queryForObject("SELECT pg_advisory_xact_lock(754302)",Map.of(),Object.class);
        var p=new HashMap<String,Object>();
        p.put("key",review.name().strip().toLowerCase(Locale.ROOT));p.put("name",review.name().strip());p.put("origin",review.origin());
        p.put("hq",Json.encode(review.headquartersCountries()));p.put("ownership",review.ownership());p.put("industry",review.industry());
        p.put("urls",Json.encode(review.evidenceUrls()));p.put("basis",review.basis());p.put("on",review.verifiedOn());p.put("status",review.status());
        db.update("""
            INSERT INTO employer_reviews(company_key,name,origin,headquarters_countries,ownership,industry,evidence_urls,basis,verified_on,status)
            VALUES (:key,:name,:origin,CAST(:hq AS jsonb),:ownership,:industry,CAST(:urls AS jsonb),:basis,:on,:status)
            ON CONFLICT(company_key) DO UPDATE SET name=excluded.name,origin=excluded.origin,
              headquarters_countries=excluded.headquarters_countries,ownership=excluded.ownership,industry=excluded.industry,
              evidence_urls=excluded.evidence_urls,basis=excluded.basis,verified_on=excluded.verified_on,status=excluded.status,
              revision=employer_reviews.revision+1,updated_at=now()
            """,p);
        return Map.of("saved",true,"matching","pending_refresh");
    }
    static Map<String,Object> apply(Map<String,Object> payload,Object value) {
        var result=new LinkedHashMap<>(payload);var facts=Json.map(value);
        boolean verified="verified".equals(facts.get("status"));
        result.put("company_type_verified",verified);
        result.put("company_type",verified?("foreign".equals(facts.get("origin"))?"foreign":facts.get("ownership")):"unknown");
        return result;
    }
    public List<Map<String,Object>> all() {return db.queryForList("SELECT to_jsonb(e) AS facts FROM employer_reviews e ORDER BY name",Map.of()).stream().map(row->Json.map(row.get("facts"))).toList();}
}
