#include "game_config.h"

#include <cstdio>
#include <map>
#include <sstream>
#include <vector>

static std::string trim(const std::string &s) {
    size_t a = s.find_first_not_of(" \t\r"), b = s.find_last_not_of(" \t\r");
    return a == std::string::npos ? "" : s.substr(a, b - a + 1);
}

static std::string hex32(uint32_t v) {
    char b[16];
    std::snprintf(b, sizeof b, "0x%08X", v);
    return b;
}

static std::string quoted(const std::string &v) {
    std::string out = "\"";
    for (char c : v) {
        if (c == '"' || c == '\\') out += '\\';
        out += c;
    }
    return out + "\"";
}

std::string ps1ios_game_toml_for_disc(const std::string &toml, const ps1_disc_info &d,
                                      const std::string &disc_rel) {
    std::string boot = d.boot;
    size_t slash = boot.find_last_of("\\/");
    if (slash != std::string::npos) boot = boot.substr(slash + 1);
    const std::string title = d.serial[0] ? d.serial : boot;

    // Keys of [game] this function owns, in output order.
    std::vector<std::pair<std::string, std::string>> set = {
        {"name", quoted(title)},
        {"exe", quoted("disc/" + boot)},
        {"disc", quoted(disc_rel)},
        {"load_address", quoted(hex32(d.load_address))},
        {"entry_pc", quoted(hex32(d.entry_pc))},
        {"text_size", quoted(hex32((d.text_size + 0xFFFu) & ~0xFFFu))},
        {"stack_base", quoted(hex32(d.stack_base ? d.stack_base : 0x801FFFF0u))},
    };
    // No serial (PSX.EXE discs): leave id out, so the runtime has no expected serial.
    if (d.serial[0]) set.insert(set.begin(), {"id", quoted(d.serial)});
    std::map<std::string, bool> owned = {{"id", true}, {"name", true}, {"exe", true}, {"disc", true},
                                         {"load_address", true}, {"entry_pc", true},
                                         {"text_size", true}, {"stack_base", true}};

    std::istringstream in(toml);
    std::string line, section, out;
    bool wrote_game = false, dropping = false;
    auto emit_game = [&]() {
        for (auto &kv : set) out += kv.first + " = " + kv.second + "\n";
        wrote_game = true;
    };
    while (std::getline(in, line)) {
        std::string st = trim(line);
        if (!st.empty() && st[0] == '[') {
            size_t e = st.find(']');
            std::string name = st.substr(1, e == std::string::npos ? std::string::npos : e - 1);
            while (!name.empty() && name[0] == '[') name = name.substr(1);   // [[array of tables]]
            section = name;
            dropping = name == "prepare_disc" || name == "netplay" ||
                       name.rfind("prepare_disc.", 0) == 0 || name.rfind("netplay.", 0) == 0;
            if (dropping) continue;
            out += line + "\n";
            if (section == "game") emit_game();
            continue;
        }
        if (dropping) continue;
        if (section == "game") {
            size_t eq = st.find('=');
            if (eq != std::string::npos && owned.count(trim(st.substr(0, eq)))) continue;
        }
        out += line + "\n";
    }
    if (!wrote_game) {
        out += "\n[game]\n";
        emit_game();
    }
    return out;
}
