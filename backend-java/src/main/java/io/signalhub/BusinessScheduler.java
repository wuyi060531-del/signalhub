package io.signalhub;
import org.springframework.stereotype.Component;
import org.springframework.scheduling.annotation.Scheduled;
@Component
public class BusinessScheduler {
    private final BusinessService service;
    public BusinessScheduler(BusinessService service) {this.service=service;}
    @Scheduled(fixedDelay=60000,initialDelay=60000)
    public void scheduledRefresh() {
        // 必须经过另一 Bean 的事务代理；同类调用 refresh 会绕过 @Transactional。
        try {service.refresh();}
        catch(Exception e) {org.slf4j.LoggerFactory.getLogger(getClass()).warn("匹配/提醒任务失败：{}",e.getClass().getSimpleName());}
    }
}
