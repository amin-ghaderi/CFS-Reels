use serde::Deserialize;

pub const READY_EVENT: &str = "amix.engine.ready";
pub const LOOPBACK_HOST: &str = "127.0.0.1";

#[derive(Clone, PartialEq, Eq)]
pub struct ReadyRecord {
    pub host: String,
    pub port: u16,
    pub token: String,
}

impl std::fmt::Debug for ReadyRecord {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ReadyRecord")
            .field("host", &self.host)
            .field("port", &self.port)
            .field("token", &"[redacted]")
            .finish()
    }
}

#[derive(Deserialize)]
struct RawReady {
    event: String,
    host: String,
    port: u16,
    token: String,
}

/// The first non-empty stdout line must be the ready record. Later lines are not searched.
pub fn accept_first_record(stdout: &str) -> Result<ReadyRecord, String> {
    for line in stdout.lines() {
        if line.trim().is_empty() {
            continue;
        }
        return parse_ready_line(line);
    }
    Err("Engine produced no ready record.".into())
}

pub fn parse_ready_line(line: &str) -> Result<ReadyRecord, String> {
    let raw: RawReady = serde_json::from_str(line.trim()).map_err(|_| {
        "Engine startup record was not the expected ready event.".to_string()
    })?;
    if raw.event != READY_EVENT {
        return Err("Engine startup record was not the expected ready event.".into());
    }
    if raw.host != LOOPBACK_HOST {
        return Err("Engine ready record did not bind to 127.0.0.1.".into());
    }
    if raw.port == 0 {
        return Err("Engine ready record did not include a port.".into());
    }
    if raw.token.trim().is_empty() {
        return Err("Engine ready record did not include a session token.".into());
    }
    Ok(ReadyRecord {
        host: raw.host,
        port: raw.port,
        token: raw.token,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid() -> String {
        r#"{"event":"amix.engine.ready","host":"127.0.0.1","port":54321,"token":"session-token"}"#
            .into()
    }

    #[test]
    fn accepts_a_valid_record() {
        let record = parse_ready_line(&valid()).unwrap();
        assert_eq!(record.host, "127.0.0.1");
        assert_eq!(record.port, 54321);
        assert_eq!(record.token, "session-token");
        let rendered = format!("{record:?}");
        assert!(!rendered.contains("session-token"));
    }

    #[test]
    fn rejects_the_wrong_event() {
        let line = r#"{"event":"amix.engine.log","host":"127.0.0.1","port":1,"token":"abc"}"#;
        assert!(parse_ready_line(line).is_err());
    }

    #[test]
    fn rejects_invalid_json() {
        assert!(parse_ready_line("INFO engine listening").is_err());
        assert!(parse_ready_line("{").is_err());
    }

    #[test]
    fn rejects_a_missing_port() {
        let line = r#"{"event":"amix.engine.ready","host":"127.0.0.1","token":"abc"}"#;
        assert!(parse_ready_line(line).is_err());
    }

    #[test]
    fn rejects_a_missing_token() {
        let line = r#"{"event":"amix.engine.ready","host":"127.0.0.1","port":9}"#;
        assert!(parse_ready_line(line).is_err());
        let empty = r#"{"event":"amix.engine.ready","host":"127.0.0.1","port":9,"token":"  "}"#;
        assert!(parse_ready_line(empty).is_err());
    }

    #[test]
    fn does_not_skip_an_unexpected_line_to_find_readiness() {
        let stdout = format!("INFO engine starting\n{}", valid());
        assert!(accept_first_record(&stdout).is_err());
    }

    #[test]
    fn skips_blank_lines_before_the_record() {
        let stdout = format!("\n  \n{}\n", valid());
        assert!(accept_first_record(&stdout).is_ok());
    }
}
