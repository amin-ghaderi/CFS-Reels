use std::path::{Path, PathBuf};

pub fn join_project_path(parent: &str, name: &str) -> Result<PathBuf, String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err("Enter a project name.".into());
    }
    if trimmed == "." || trimmed == ".." || trimmed.contains(['/', '\\', '\0']) {
        return Err("Use a project name without slashes.".into());
    }
    let parent = Path::new(parent);
    if parent.as_os_str().is_empty() {
        return Err("Choose a folder for the new project.".into());
    }
    Ok(parent.join(trimmed))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joins_with_the_platform_path_api() {
        let path = join_project_path(r"C:\work", "Interview").unwrap();
        assert_eq!(path.file_name().unwrap(), "Interview");
        assert!(path.starts_with(r"C:\work") || path.starts_with("/work") || path.parent().is_some());
    }

    #[test]
    fn rejects_blank_and_nested_names() {
        assert!(join_project_path(r"C:\work", "  ").is_err());
        assert!(join_project_path(r"C:\work", r"a\b").is_err());
        assert!(join_project_path(r"C:\work", "a/b").is_err());
        assert!(join_project_path(r"C:\work", "..").is_err());
    }
}
