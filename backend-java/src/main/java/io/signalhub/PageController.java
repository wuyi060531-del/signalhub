package io.signalhub;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.core.env.Environment;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.web.csrf.CsrfToken;
import java.util.*;
@Controller
public class PageController {
    private final Environment environment;
    public PageController(Environment environment) { this.environment=environment; }
    private static final Map<String,String> TITLES=Map.ofEntries(Map.entry("overview","总览"),Map.entry("domestic","国内求职"),Map.entry("foreign","外企求职"),Map.entry("opportunities","海外机会"),Map.entry("technology","技术情报"),Map.entry("skills","JD 技能分析"),Map.entry("subscriptions","我的订阅"),Map.entry("applications","投递管理"),Map.entry("monitor","数据源与任务"),Map.entry("settings","求职档案与设置"),Map.entry("import","手动导入"),Map.entry("detail","信息详情"));
    @GetMapping({"/","/view/{section}"}) public String page(@PathVariable(required=false) String section,@RequestParam(required=false) Long id,Model model,CsrfToken csrf) {
        section=section==null?"overview":section;
        if(!TITLES.containsKey(section))throw new NoSuchElementException();
        // 重播入口只在显式启用 dev 配置时输出，不依赖客户端域名猜测环境。
        model.addAttribute("startupReplay",environment.matchesProfiles("dev"));
        model.addAttribute("section",section);model.addAttribute("title",TITLES.get(section));model.addAttribute("itemId",id);model.addAttribute("csrf",csrf.getToken());model.addAttribute("csrfHeader",csrf.getHeaderName());return "console";
    }
}
