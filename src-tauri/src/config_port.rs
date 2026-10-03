pub(crate) fn parse_overlay_port(raw: &str) -> Option<u16> {
    let value: toml::Value = toml::from_str(raw).ok()?;
    value
        .get("overlay")
        .and_then(|overlay| overlay.get("port"))
        .and_then(|port| port.as_integer())
        .and_then(|port| u16::try_from(port).ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlay_port_reads_a_complete_config_document() {
        assert_eq!(parse_overlay_port("[overlay]\nport = 18765\n"), Some(18765));
        assert_eq!(parse_overlay_port("[overlay]\nport = 70000\n"), None);
        assert_eq!(parse_overlay_port("[overlay\nport = 18765\n"), None);
    }
}
