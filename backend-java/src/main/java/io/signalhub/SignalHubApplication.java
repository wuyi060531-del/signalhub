package io.signalhub;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;
@SpringBootApplication
@EnableScheduling
public class SignalHubApplication {
    public static void main(String[] args) { SpringApplication.run(SignalHubApplication.class,args); }
}
