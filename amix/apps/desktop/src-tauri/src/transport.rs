use std::io::Read;
use std::time::Duration;

use crate::ready::LOOPBACK_HOST;

#[derive(Clone, Debug)]
pub struct RawHttp {
    pub status: u16,
    pub body: String,
}

pub fn validate_request(method: &str, path: &str) -> Result<(), String> {
    if method != "GET" && method != "POST" {
        return Err("The desktop can only send engine GET and POST requests.".into());
    }
    if !path.starts_with("/v1/")
        || path.contains("..")
        || path.contains('?')
        || path.contains('#')
        || path.contains('\\')
        || path.contains('\0')
        || path.contains("//")
    {
        return Err("That engine address is not allowed.".into());
    }
    Ok(())
}

pub fn engine_http(
    port: u16,
    token: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    timeout: Duration,
) -> Result<RawHttp, String> {
    validate_request(method, path)?;
    if port == 0 {
        return Err("The engine is not ready.".into());
    }
    let url = format!("http://{LOOPBACK_HOST}:{port}{path}");
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(3))
        .timeout_read(timeout)
        .redirects(0)
        .build();
    let request = agent
        .request(method, &url)
        .set("Authorization", &format!("Bearer {token}"))
        .set("Accept", "application/json");
    let result = if let Some(payload) = body {
        request.set("Content-Type", "application/json").send_string(payload)
    } else {
        request.call()
    };
    match result {
        Ok(response) => Ok(RawHttp {
            status: response.status(),
            body: read_limited(response),
        }),
        Err(ureq::Error::Status(status, response)) => Ok(RawHttp {
            status,
            body: read_limited(response),
        }),
        Err(_) => Err("The engine did not respond.".into()),
    }
}

fn read_limited(response: ureq::Response) -> String {
    let mut buffer = Vec::new();
    let _ = response
        .into_reader()
        .take(1_000_000)
        .read_to_end(&mut buffer);
    String::from_utf8_lossy(&buffer).into_owned()
}

pub fn redact(line: &str, token: Option<&str>) -> String {
    let mut redacted = line.replace("Authorization", "[redacted]");
    if let Some(secret) = token {
        if !secret.is_empty() {
            redacted = redacted.replace(secret, "[redacted]");
        }
    }
    redacted
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_only_loopback_engine_paths() {
        assert!(validate_request("GET", "/v1/health").is_ok());
        assert!(validate_request("POST", "/v1/projects/create").is_ok());
        assert!(validate_request("PUT", "/v1/health").is_err());
        assert!(validate_request("GET", "/v1/../secret").is_err());
        assert!(validate_request("GET", "/v1/health?token=1").is_err());
        assert!(validate_request("GET", "http://example.com/v1/health").is_err());
    }

    #[test]
    fn redacts_authorization_and_the_session_token() {
        let line = "Authorization: Bearer session-token";
        let redacted = redact(line, Some("session-token"));
        assert!(!redacted.contains("session-token"));
        assert!(!redacted.contains("Authorization"));
    }
}
