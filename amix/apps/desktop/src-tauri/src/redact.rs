/// Remove secret-shaped fields before a React request reaches the engine.
pub fn strip_secret_fields(body: &str) -> String {
    let Ok(mut value) = serde_json::from_str::<serde_json::Value>(body) else {
        return body.to_string();
    };
    scrub(&mut value);
    serde_json::to_string(&value).unwrap_or_else(|_| body.to_string())
}

fn scrub(value: &mut serde_json::Value) {
    match value {
        serde_json::Value::Object(map) => {
            map.retain(|key, _| !is_secret_key(key));
            for child in map.values_mut() {
                scrub(child);
            }
        }
        serde_json::Value::Array(items) => {
            for item in items {
                scrub(item);
            }
        }
        _ => {}
    }
}

fn is_secret_key(key: &str) -> bool {
    matches!(
        key.to_ascii_lowercase().as_str(),
        "api_key"
            | "apikey"
            | "token"
            | "password"
            | "secret"
            | "authorization"
            | "credential"
            | "ffmpeg"
            | "ffprobe"
            | "ffmpeg_path"
            | "ffprobe_path"
            | "executable"
            | "model_path"
            | "local_path"
    )
}

#[cfg(test)]
mod tests {
    use super::strip_secret_fields;

    #[test]
    fn secret_fields_are_removed_and_the_rest_remains() {
        let cleaned = strip_secret_fields(r#"{"name":"Loop","api_key":"sk-test","nested":{"token":"x"}}"#);
        assert!(cleaned.contains("Loop"));
        assert!(!cleaned.contains("sk-test"));
        assert!(!cleaned.contains("\"token\""));
    }

    #[test]
    fn a_non_json_body_is_left_unchanged() {
        assert_eq!(strip_secret_fields("not-json"), "not-json");
    }
}
