//! The same palette lib/ui.py reads from the profile's `[deck] theme` (or
//! PHOSPHOR_THEME), so a banner drawn here looks like any other phosphor
//! tool's -- not a fixed color scheme of its own.

use std::collections::HashMap;

pub struct Palette {
    pub fg: &'static str,
    pub dim: &'static str,
    pub amb: &'static str,
    pub red: &'static str,
    pub rst: &'static str,
}

fn rgb(r: u8, g: u8, b: u8) -> String {
    format!("\x1b[38;2;{};{};{}m", r, g, b)
}

/// (fg, dim, warn, bad) rgb triples, one row per theme -- lib/ui.py's own
/// PALETTES table, just the four colors this binary's banners actually use.
fn table() -> HashMap<&'static str, [(u8, u8, u8); 4]> {
    HashMap::from([
        ("p31", [(168, 229, 176), (74, 110, 83), (255, 176, 0), (255, 51, 68)]),
        ("p3", [(240, 200, 140), (112, 78, 28), (255, 110, 40), (255, 51, 51)]),
        ("p4", [(200, 208, 214), (84, 90, 96), (255, 176, 0), (255, 51, 68)]),
        ("paper", [(26, 26, 26), (120, 120, 120), (107, 74, 0), (138, 26, 34)]),
    ])
}

fn alias(t: &str) -> &str {
    match t {
        "green" => "p31",
        "amber" => "p3",
        "white" => "p4",
        other => other,
    }
}

/// PHOSPHOR_THEME, else the profile's [deck] theme, else p31 -- same order
/// lib/ui.py's theme_name() resolves in. Takes the env override as a plain
/// argument (not read internally) so tests never race on a shared env var.
pub fn resolve(env_override: Option<&str>, profile_theme: Option<&str>) -> Palette {
    let name = alias(env_override.or(profile_theme).unwrap_or("p31")).to_string();
    let t = table();
    let row = t.get(name.as_str()).copied().unwrap_or(t["p31"]);
    // Leaked on purpose: one Palette, for the life of a one-shot CLI process.
    Palette {
        fg: Box::leak(rgb(row[0].0, row[0].1, row[0].2).into_boxed_str()),
        dim: Box::leak(rgb(row[1].0, row[1].1, row[1].2).into_boxed_str()),
        amb: Box::leak(rgb(row[2].0, row[2].1, row[2].2).into_boxed_str()),
        red: Box::leak(rgb(row[3].0, row[3].1, row[3].2).into_boxed_str()),
        rst: "\x1b[0m",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_to_p31_green() {
        let p = resolve(None, None);
        assert_eq!(p.fg, rgb(168, 229, 176));
    }

    #[test]
    fn profile_theme_wins_over_the_default() {
        let p = resolve(None, Some("p3"));
        assert_eq!(p.fg, rgb(240, 200, 140));
    }

    #[test]
    fn env_override_wins_over_the_profile() {
        let p = resolve(Some("p4"), Some("p3"));
        assert_eq!(p.fg, rgb(200, 208, 214));
    }

    #[test]
    fn an_alias_resolves_the_same_as_its_real_name() {
        assert_eq!(resolve(None, Some("amber")).fg, resolve(None, Some("p3")).fg);
    }

    #[test]
    fn an_unknown_theme_falls_back_to_p31_like_ui_py_does() {
        let p = resolve(None, Some("not-a-real-theme"));
        assert_eq!(p.fg, rgb(168, 229, 176));
    }
}
