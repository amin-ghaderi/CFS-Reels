/// OS credential boundary. React never receives the stored secret.
use keyring::Entry;

const SERVICE: &str = "AMIX";

pub trait CredentialVault {
    fn set(&self, account: &str, secret: &str) -> Result<(), String>;
    fn get(&self, account: &str) -> Result<Option<String>, String>;
    fn delete(&self, account: &str) -> Result<(), String>;
}

pub struct KeyringVault;

impl CredentialVault for KeyringVault {
    fn set(&self, account: &str, secret: &str) -> Result<(), String> {
        Entry::new(SERVICE, account)
            .map_err(|_| "The credential store is unavailable.".to_string())?
            .set_password(secret)
            .map_err(|_| "The credential could not be stored.".to_string())
    }

    fn get(&self, account: &str) -> Result<Option<String>, String> {
        match Entry::new(SERVICE, account) {
            Ok(entry) => match entry.get_password() {
                Ok(secret) => Ok(Some(secret)),
                Err(keyring::Error::NoEntry) => Ok(None),
                Err(_) => Err("The credential store is unavailable.".into()),
            },
            Err(_) => Err("The credential store is unavailable.".into()),
        }
    }

    fn delete(&self, account: &str) -> Result<(), String> {
        match Entry::new(SERVICE, account) {
            Ok(entry) => match entry.delete_credential() {
                Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
                Err(_) => Err("The credential could not be removed.".into()),
            },
            Err(_) => Err("The credential store is unavailable.".into()),
        }
    }
}

#[cfg(test)]
pub struct MemoryVault {
    values: std::sync::Mutex<std::collections::HashMap<String, String>>,
}

#[cfg(test)]
impl MemoryVault {
    pub fn new() -> Self {
        Self {
            values: std::sync::Mutex::new(std::collections::HashMap::new()),
        }
    }
}

#[cfg(test)]
impl CredentialVault for MemoryVault {
    fn set(&self, account: &str, secret: &str) -> Result<(), String> {
        self.values.lock().expect("vault").insert(account.to_string(), secret.to_string());
        Ok(())
    }

    fn get(&self, account: &str) -> Result<Option<String>, String> {
        Ok(self.values.lock().expect("vault").get(account).cloned())
    }

    fn delete(&self, account: &str) -> Result<(), String> {
        self.values.lock().expect("vault").remove(account);
        Ok(())
    }
}

pub fn credential_account(credential_ref: &str) -> String {
    format!("provider:{credential_ref}")
}

#[cfg(test)]
mod tests {
    use super::{CredentialVault, MemoryVault, credential_account};

    #[test]
    fn memory_vault_sets_replaces_and_removes_without_echoing_into_a_status() {
        let vault = MemoryVault::new();
        let account = credential_account("provider:1");
        vault.set(&account, "sk-one").unwrap();
        assert_eq!(vault.get(&account).unwrap().as_deref(), Some("sk-one"));
        vault.set(&account, "sk-two").unwrap();
        assert_eq!(vault.get(&account).unwrap().as_deref(), Some("sk-two"));
        let status = serde_json::json!({ "credential_configured": vault.get(&account).unwrap().is_some() });
        let text = status.to_string();
        assert!(text.contains("true"));
        assert!(!text.contains("sk-two"));
        vault.delete(&account).unwrap();
        assert_eq!(vault.get(&account).unwrap(), None);
    }
}
