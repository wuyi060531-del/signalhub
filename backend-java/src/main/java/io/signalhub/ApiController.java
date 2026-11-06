package io.signalhub;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import jakarta.validation.Valid;
import jakarta.validation.Validator;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.type.TypeReference;
import java.io.*;
import java.util.*;
@RestController
@RequestMapping("/api")
public class ApiController {
    private final ItemRepository items;
    private final BusinessService service;
    private final ObjectMapper mapper;
    private final Validator validator;
    public ApiController(ItemRepository items,BusinessService service,ObjectMapper mapper,Validator validator) {this.items=items;this.service=service;this.mapper=mapper;this.validator=validator;}
    @org.springframework.beans.factory.annotation.Autowired EmployerRegistry employers;
    @org.springframework.beans.factory.annotation.Autowired TranslationQueue translationQueue;
    @GetMapping("/translations/status") public Object translationStatus() {return translationQueue.status();}
    @PostMapping("/translations") public Object translations(@Valid @RequestBody TranslationQueue.Request request) {return translationQueue.request(request);}
    @GetMapping("/reading") public Object reading(@RequestParam List<Long> ids) {return items.readingMany(ids);}
    @GetMapping("/employers") public Object employers() {return employers.all();}
    @PutMapping("/employers/review") public Object employerReview(@Valid @RequestBody EmployerRegistry.Review review) {return employers.save(review);}
    @GetMapping("/classification-summary") public Object classificationSummary() {return items.classificationSummary();}
    @GetMapping("/job-overview") public Object jobOverview() {return items.jobOverview();}
    @GetMapping("/job-coverage") public Object jobCoverage(@RequestParam(defaultValue="mainland") String domain) {return items.jobCoverage(domain);}
    @GetMapping("/health") public Map<String,Object> health() {return service.health();}
    @GetMapping("/items") public Map<String,Object> items(@RequestParam Map<String,String> query,@RequestParam(defaultValue="0") int page,@RequestParam(defaultValue="20") int size) {return items.search(query,page,size);}
    @GetMapping("/items/{id}") public Map<String,Object> detail(@PathVariable long id) {return items.detail(id);}
    @GetMapping("/skills") public Map<String,Object> skills(@RequestParam Map<String,String> query) {return items.stats(query);}
    @GetMapping("/profile") public Map<String,Object> profile() {return service.profile();}
    @PutMapping("/profile") public Map<String,Object> profile(@Valid @RequestBody Contracts.Profile profile) {return service.saveProfile(profile);}
    @PostMapping("/imports") public Map<String,Object> imports(@Valid @RequestBody Contracts.ImportRequest request) {return Map.of("taskId",service.importRecords(request),"state","pending");}
    @PostMapping("/demo") public Map<String,Object> demo() throws IOException {
        try(var input=getClass().getResourceAsStream("/demo.json")) {
            List<Map<String,Object>> records=mapper.readValue(input,new TypeReference<>(){});
            return Map.of("taskId",service.enqueue("import",2,Map.of("records",records)),"state","pending");
        }
    }
    @PostMapping("/imports/file") public Map<String,Object> file(@RequestParam long sourceId,@RequestParam MultipartFile file) throws IOException {
        if(file.getSize()>2*1024*1024)throw new IllegalArgumentException("文件超过2MB");
        List<Contracts.ManualItem> records;
        if(Objects.toString(file.getOriginalFilename(),"").endsWith(".json")) records=mapper.readValue(file.getInputStream(),new TypeReference<>(){});
        else if(Objects.toString(file.getOriginalFilename(),"").endsWith(".csv")) {
            try(var csv=org.apache.commons.csv.CSVFormat.DEFAULT.builder().setHeader().setSkipHeaderRecord(true).get().parse(new InputStreamReader(file.getInputStream(),java.nio.charset.StandardCharsets.UTF_8))) {
            records=new ArrayList<>();
            for(var row:csv) {
                var data=new HashMap<String,Object>(row.toMap());
                data.values().removeIf(v->v.toString().isBlank());
                for(String key:List.of("skills","categories","salary","risk_notes","locations","skill_groups","graduation_years","unparsed_skill_conditions","experience_requirements","qualification_review_notes")) {
                    if(data.get(key) instanceof String value)data.put(key,mapper.readValue(value,Object.class));
                }
                records.add(mapper.convertValue(data,Contracts.ManualItem.class));
                if(records.size()>1000)throw new IllegalArgumentException("最多1000行");
            }
            } catch(java.io.IOException | java.io.UncheckedIOException e) {throw new IllegalArgumentException("CSV格式错误",e);}
        } else throw new IllegalArgumentException("只接受CSV/JSON文件");
        var request=new Contracts.ImportRequest(sourceId,records);
        if(!validator.validate(request).isEmpty())throw new IllegalArgumentException("导入数据未通过字段校验");
        return imports(request);
    }
    @PostMapping("/matches/refresh") public Map<String,Object> refresh() {return service.refresh();}
    @GetMapping("/subscriptions") public Object subscriptions() {return service.subscriptions();}
    @PostMapping("/subscriptions") public Object subscription(@Valid @RequestBody Contracts.Subscription sub) {return Map.of("id",service.subscription(sub));}
    @PutMapping("/subscriptions/{id}") public Object updateSubscription(@PathVariable long id,@Valid @RequestBody Contracts.Subscription sub) {service.updateSubscription(id,sub);return Map.of("saved",true);}
    @GetMapping("/applications") public Object applications() {return service.applications();}
    @PutMapping("/applications/{id}") public Object application(@PathVariable long id,@Valid @RequestBody Contracts.Application app) {service.saveApplication(id,app);return Map.of("saved",true);}
    @GetMapping("/applications/{id}/history") public Object history(@PathVariable long id) {return service.history(id);}
    @GetMapping("/alerts") public Object alerts(@RequestParam(defaultValue="0") int page,@RequestParam(defaultValue="200") int size,@RequestParam(defaultValue="all") String state,@RequestParam(defaultValue="all") String type,@RequestParam(defaultValue="true") boolean includeDemo) {return service.alerts(page,size,state,type,includeDemo);}
    @GetMapping("/alerts/summary") public Object alertSummary(@RequestParam(defaultValue="all") String state,@RequestParam(defaultValue="all") String type,@RequestParam(defaultValue="true") boolean includeDemo) {return service.alertSummary(state,type,includeDemo);}
    @PutMapping("/alerts/read") public Object readAlerts(@RequestParam(defaultValue="all") String state,@RequestParam(defaultValue="all") String type,@RequestParam(defaultValue="true") boolean includeDemo,@RequestParam long throughId) {return service.readAlerts(state,type,includeDemo,throughId);}
    @PutMapping("/alerts/{id}/read") public Object read(@PathVariable long id) {service.readAlert(id);return Map.of("saved",true);}
    @GetMapping("/monitor") public Object monitor() {return service.monitoring();}
    @GetMapping("/tasks/{id}") public Object task(@PathVariable long id) {return service.task(id);}
    @PostMapping("/sources") public Object source(@Valid @RequestBody Contracts.SourceRequest source) {return Map.of("id",service.saveSource(source));}
    @PutMapping("/sources/{id}/enabled") public Object enabled(@PathVariable long id,@RequestParam boolean enabled) {service.enabled(id,enabled);return Map.of("saved",true);}
    @PostMapping("/sources/{id}/collect") public Object collect(@PathVariable long id) {return Map.of("taskId",service.enqueue("collect",id,Map.of()));}
    @GetMapping("/ai") public Object ai() {return service.aiStatus();}
    @PostMapping("/items/{id}/enrich") public Object enrich(@PathVariable long id) {items.detail(id);return Map.of("taskId",service.enqueue("enrich",1,Map.of("item_id",id)));}
}
