package io.signalhub;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CsrfFilter;
import org.springframework.web.filter.OncePerRequestFilter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Collections;
import java.util.regex.Pattern;
@Configuration
public class SecurityConfig {
    private static final Pattern LOCAL_HOST = Pattern.compile(
        "(?:localhost|127\\.0\\.0\\.1|\\[::1\\])(?::[0-9]{1,5})?", Pattern.CASE_INSENSITIVE);

    @Bean SecurityFilterChain security(HttpSecurity http) throws Exception {
        // 本地单用户：绑定 loopback，保留 CSRF，不开放 CORS；部署公网前必须添加认证。
        return http.addFilterBefore(new OncePerRequestFilter() {
                @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                        FilterChain chain) throws ServletException, IOException {
                    var hosts = Collections.list(request.getHeaders("Host"));
                    // loopback监听不足以防DNS重绑定；不信任Forwarded/X-Forwarded-Host。
                    String host = hosts.isEmpty() ? request.getServerName() : hosts.getFirst();
                    if (hosts.size() > 1 || !LOCAL_HOST.matcher(host).matches()) {
                        response.sendError(HttpServletResponse.SC_FORBIDDEN);
                        return;
                    }
                    chain.doFilter(request, response);
                }
            }, CsrfFilter.class).authorizeHttpRequests(a -> a.anyRequest().permitAll())
            .formLogin(f -> f.disable()).httpBasic(b -> b.disable())
            .headers(h -> h.contentSecurityPolicy(c -> c.policyDirectives("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'")))
            .build();
    }
}
