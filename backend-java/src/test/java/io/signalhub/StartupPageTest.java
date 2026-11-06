package io.signalhub;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import static org.hamcrest.Matchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(PageController.class)
@Import(SecurityConfig.class)
class StartupPageTest {
    @Autowired MockMvc mvc;

    @Test void normalPagesKeepBusinessScriptsAndDoNotExposeReplay() throws Exception {
        for (String route : new String[]{"/", "/view/domestic", "/view/settings"}) {
            mvc.perform(get(route)).andExpect(status().isOk())
                .andExpect(content().string(containsString("aria-labelledby=\"startup-title\" hidden")))
                .andExpect(content().string(containsString("/app.js\" defer></script>\n    <script src=\"/startup.js\" defer")))
                .andExpect(content().string(not(containsString("id=\"startup-replay\""))))
                .andExpect(header().string("Content-Security-Policy", containsString("script-src 'self'")));
        }
    }

    @Test void startupScriptIsServedWithExistingSecurityPolicy() throws Exception {
        mvc.perform(get("/startup.js")).andExpect(status().isOk())
            .andExpect(content().string(containsString("sessionStorage")));
        mvc.perform(get("/view/missing")).andExpect(status().isNotFound());
    }
}

@WebMvcTest(PageController.class)
@Import(SecurityConfig.class)
@ActiveProfiles("dev")
class StartupDevPageTest {
    @Autowired MockMvc mvc;

    @Test void developmentProfileIncludesManualReplayOnEveryConsolePage() throws Exception {
        for (String route : new String[]{"/", "/view/monitor"}) {
            mvc.perform(get(route)).andExpect(status().isOk())
                .andExpect(content().string(containsString("id=\"startup-replay\"")))
                .andExpect(content().string(containsString("重播启动动画")));
        }
    }
}
