package io.signalhub;
/** 仅用于由应用生成、不包含用户原文或密钥的可展示校验信息。 */
public final class InputValidationException extends IllegalArgumentException {
    public InputValidationException(String message) { super(message); }
}
