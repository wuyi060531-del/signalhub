package io.signalhub;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.dao.*;
import java.util.*;
@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(InputValidationException.class)
    ResponseEntity<?> userInput(InputValidationException e) {return ResponseEntity.badRequest().body(Map.of("error",e.getMessage()));}
    @ExceptionHandler({IllegalArgumentException.class,java.time.DateTimeException.class,MethodArgumentNotValidException.class,HttpMessageNotReadableException.class,tools.jackson.core.JacksonException.class,org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class,org.springframework.web.multipart.MaxUploadSizeExceededException.class})
    ResponseEntity<?> invalid(Exception e) {
        String message="输入校验失败，请检查字段、JSON格式和日期";
        if(e instanceof MethodArgumentNotValidException validation) {
            String fields=validation.getBindingResult().getFieldErrors().stream().map(error -> error.getField()).distinct().sorted().collect(java.util.stream.Collectors.joining("、"));
            if(!fields.isBlank()) message="输入校验失败，请检查字段："+fields;
        }
        return ResponseEntity.badRequest().body(Map.of("error",message));
    }
    @ExceptionHandler({NoSuchElementException.class,EmptyResultDataAccessException.class})
    ResponseEntity<?> missing(Exception e) {return ResponseEntity.status(404).body(Map.of("error","记录不存在"));}
    @ExceptionHandler(DataIntegrityViolationException.class)
    ResponseEntity<?> conflict(Exception e) {return ResponseEntity.status(409).body(Map.of("error","数据冲突或引用的记录不存在"));}
    @ExceptionHandler(Exception.class)
    ResponseEntity<?> unexpected(Exception e) {
        // Spring的请求方法、必填参数、媒体类型和资源错误仍是4xx；不泄露框架异常详情。
        if(e instanceof org.springframework.web.ErrorResponse response && response.getStatusCode().is4xxClientError())
            return ResponseEntity.status(response.getStatusCode()).headers(response.getHeaders())
                .body(Map.of("error","请求方式、参数、内容类型或资源地址不正确，请检查API说明"));
        org.slf4j.LoggerFactory.getLogger(getClass()).error("请求失败 {}",e.getClass().getSimpleName());
        return ResponseEntity.status(500).body(Map.of("error","服务暂时不可用，请检查任务监控和本地日志"));
    }
}
