#!/usr/bin/env python3
"""Contracts for the epic levelling reform.

- Experience alone levels a character to 56 on a curve where every level costs
  more than the one before; levels 51-56 cost no epic points.
- Epic points are banked only from epic.bank.minLevel (56). From
  epic.gain.minLevel (50) up to it, awards still feed artifacts and guild
  prestige but are paid as experience (epics x epic.convert.exp.<level>).
- Epic skills cost epic.skill.costMultiplier (5); refunds stay at 3.
- Artifact feeding rates are properties with the proposed defaults, retunable in
  game with the artifeed command; non-PvP feeds stop at a 72-hour ceiling.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from _paths import ROOT, source


def _properties() -> dict[str, float]:
    values: dict[str, float] = {}
    for line in (ROOT / "lib" / "duris.properties").read_text().splitlines():
        if line.startswith(("#", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = float(value)
    return values


PROPS = _properties()


def _flat(text: str) -> str:
    return "".join(text.split())


def _definition(name: str, signature: str) -> str:
    """A function definition, skipping prototypes: its signature to the closing brace in column 0."""
    text = source(name).read_text()
    at = text.find(signature)
    while at >= 0:
        brace, semicolon = text.find("{", at), text.find(";", at)
        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            return text[at:text.index("\n}\n", brace) + 2]
        at = text.find(signature, at + 1)
    raise AssertionError(f"{name}: no definition for {signature}")


def _compile_and_run(code: str, extra_sources: tuple[Path, ...] = ()) -> None:
    with tempfile.TemporaryDirectory(prefix="duris-epic-reform-") as directory:
        harness = Path(directory) / "harness.cpp"
        binary = Path(directory) / "harness"
        harness.write_text(code)
        subprocess.run(
            ["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
             "-fno-omit-frame-pointer", "-no-pie", "-I" + str(ROOT / "src"), "-x", "c++",
             str(harness), *[str(path) for path in extra_sources], "-o", str(binary)],
            check=True)
        subprocess.run([str(binary)], check=True)


# ------------------------------------------------------------------ experience table

OLD_BANDS = ((2, 5, 2000), (6, 10, 8000), (11, 15, 25000), (16, 20, 100000),
             (21, 25, 400000), (26, 30, 1600000), (31, 35, 3000000), (36, 40, 6000000),
             (41, 45, 12600000), (46, 50, 20000000))


def test_every_level_costs_more_than_the_one_before() -> None:
    table = [PROPS[f"exp.required.{level:02d}"] for level in range(1, 57)]
    assert all(later > earlier for earlier, later in zip(table, table[1:]))
    assert PROPS["exp.maxExpLevel"] == 56


def test_levels_2_to_50_keep_each_old_band_total() -> None:
    for low, high, old in OLD_BANDS:
        new = sum(PROPS[f"exp.required.{level:02d}"] for level in range(low, high + 1))
        was = old * (high - low + 1)
        assert abs(new - was) / was <= 0.01, (low, high, new, was)


def test_levels_51_to_56_are_exp_only_and_steeper() -> None:
    top = [PROPS[f"exp.required.{level}"] for level in range(51, 57)]
    # The time-equivalent of the old 40M-plus-epics price, unchanged in total.
    assert sum(top) == 793_900_000
    assert top[0] / PROPS["exp.required.50"] > 1.8
    assert all(1.4 < later / earlier < 1.5 for earlier, later in zip(top, top[1:]))
    for level in range(51, 57):
        assert PROPS[f"epic.forLevel.{level}"] == 0


# ------------------------------------------------------------------ banking and conversion

def test_properties_ship_the_bank_level_conversion_and_skill_prices() -> None:
    assert PROPS["epic.gain.minLevel"] == 50
    assert PROPS["epic.bank.minLevel"] == 56
    expected = {50: 8500, 51: 5500, 52: 5500, 53: 5000, 54: 5000, 55: 5000}
    for level, rate in expected.items():
        assert PROPS[f"epic.convert.exp.{level}"] == rate
    assert PROPS["epic.skill.costMultiplier"] == 5
    assert PROPS["epic.skill.refundMultiplier"] == 3


def test_bank_helpers_conversion_and_multipliers_at_runtime() -> None:
    helpers = "\n".join(_definition("world/epic.c", signature) for signature in (
        "int epic_bank_min_level()", "bool epic_level_can_bank(P_char ch)",
        "int epic_conversion_exp_per_epic(int level)", "int epic_skill_cost_multiplier()",
        "int epic_skill_refund_multiplier()"))
    _compile_and_run(r'''
#include <cstdio>
#include <map>
#include <string>
#define MAXLVL 62
#define BOUNDED(low, value, high) ((value) < (low) ? (low) : (value) > (high) ? (high) : (value))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
struct test_player { struct { int level; } player; };
using P_char = test_player *;
#define GET_LEVEL(ch) ((ch)->player.level)
static std::map<std::string, float> props;
float get_property(const char *key, double fallback, bool) {
    const auto found = props.find(key);
    return found == props.end() ? static_cast<float>(fallback) : found->second;
}
float get_property(const char *key, double fallback) { return get_property(key, fallback, true); }
int get_property(const char *key, int fallback) {
    return static_cast<int>(get_property(key, static_cast<double>(fallback), true));
}
''' + helpers + r'''
int main() {
    if (epic_bank_min_level() != 56) return 1;
    test_player below{{55}}, bank{{56}};
    if (epic_level_can_bank(&below) || !epic_level_can_bank(&bank) || epic_level_can_bank(nullptr))
        return 2;
    const int defaults[] = { 8500, 5500, 5500, 5000, 5000, 5000 };
    for (int level = 50; level <= 55; ++level)
        if (epic_conversion_exp_per_epic(level) != defaults[level - 50]) return 3;
    // A level outside the table uses the nearest default; a property overrides; never negative.
    if (epic_conversion_exp_per_epic(40) != 8500 || epic_conversion_exp_per_epic(60) != 5000) return 4;
    props["epic.convert.exp.52"] = 1234;
    props["epic.convert.exp.53"] = -7;
    if (epic_conversion_exp_per_epic(52) != 1234 || epic_conversion_exp_per_epic(53) != 0) return 5;
    if (epic_skill_cost_multiplier() != 5 || epic_skill_refund_multiplier() != 3) return 6;
    props["epic.skill.costMultiplier"] = 0;
    props["epic.skill.refundMultiplier"] = 500;
    if (epic_skill_cost_multiplier() != 1 || epic_skill_refund_multiplier() != 100) return 7;
    props["epic.bank.minLevel"] = 99;
    if (epic_bank_min_level() != MAXLVL) return 8;
    std::puts("epic bank helpers, conversion rates and skill multipliers passed");
    return 0;
}
''')


def test_awards_below_the_bank_level_feed_then_convert() -> None:
    gain = _flat(_definition("world/epic.c", "void gain_epic(P_char ch, int type, int data, int amount)"))
    branch = gain.index(_flat("if (!epic_level_can_bank(ch))"))
    assert branch < gain.index("artifact_guild_transaction_submit(ch,operation_id,amount,type)")
    assert gain.index("epic_award_converted(ch,context);return;") < gain.index(
        "epic_transaction_submit_identified(")
    converted = _flat(_definition("world/epic.c", "static void epic_award_converted("))
    assert "gameplay_read_state_add_completed_zone" in converted
    assert "epic_conversion_exp_per_epic(GET_LEVEL(ch))" in converted
    assert "gain_exp(ch,NULL," in converted and "EXP_EPIC)" in converted


def test_stones_record_converted_members_but_credit_them_nothing() -> None:
    stone = _flat(_definition("world/epic.c", "int epic_stone(P_obj obj, P_char ch, int cmd, char *arg)"))
    assert "epic_level_can_bank(participant)?0:ZONE_TOUCH_AWARD_CONVERTED" in stone
    header = source("world/zone_touch_command.h").read_text()
    assert "constexpr uint8_t ZONE_TOUCH_AWARD_CONVERTED = 4;" in header
    assert "award.amount <= 0 || award.flags > 7" in source("world/zone_touch_command.c").read_text()
    repository = _flat(source("persistence/critical_command_repository.c").read_text())
    skip = repository.index("if(zone_payload.awards[i].flags&ZONE_TOUCH_AWARD_CONVERTED)continue;")
    assert skip < repository.index("zone_touch_award_command(command,i,&child)", skip)
    publish = _flat(source("world/zone_touch_transaction.c").read_text())
    assert ("if(!(entry.result.awards[i].flags&ZONE_TOUCH_AWARD_CONVERTED)&&"
            "entry.result.revisions[i]>=ch->only.pc->epic_revision)") in publish
    award = _flat(_definition("world/epic.c", "void epic_publish_stone_award("))
    assert award.index("if(award.flags&ZONE_TOUCH_AWARD_CONVERTED)") < award.index(
        "epic_award_committed(")


def test_pvp_awards_below_the_bank_level_feed_then_convert() -> None:
    fight = _flat(source("combat/fight.c").read_text())
    assert ("if(epic_level_can_bank(current))entry->epic_delta=award;"
            "elseentry->epic_converted=award;") in fight
    assert "constint64_tfed=entry.epic_delta>0?entry.epic_delta:entry.epic_converted;" in fight
    assert "static_cast<int>(fed)" in fight
    assert ("elseif(entry.epic_converted>0)epic_pay_converted_award(ch,EPIC_PVP,0,"
            "static_cast<int>(entry.epic_converted));") in fight
    command = source("combat/combat_outcome_command.c").read_text()
    assert "epic_converted" not in command, "the conversion amount is never encoded"


def test_converted_experience_is_not_doubled_by_rest() -> None:
    gain = _flat(_definition("world/limits.c", "int gain_exp("))
    assert "if(type==EXP_RESURRECT||type==EXP_EPIC){;}elseif(has_active_rested_bonus(ch,TAG_WELLRESTED))" in gain
    assert "#define EXP_EPIC 11" in source("core/structs.h").read_text()
    assert "epic_conversion = 13," in source("telemetry/telemetry_types.h").read_text()


def test_epic_potions_respecs_and_skill_prices_follow_the_bank_level() -> None:
    quaff = _flat(_definition("cmd/actoth.c", "void do_quaff("))
    assert "OBJ_VNUM(bottle)==VOBJ_EPIC_BOTTLE_EPICS&&!epic_level_can_bank(ch)" in quaff
    unmulti = _flat(_definition("cmd/actinf.c", "void unmulti(P_char ch, P_obj obj)"))
    assert unmulti.index("if(waived){unmulti_committed(ch,true,{},0,nullptr,0);return;}") < unmulti.index(
        "epic_transaction_submit(")
    unspec = _flat(_definition("classes/specializations.c", "void unspecialize(P_char ch, P_obj obj)"))
    assert unspec.index("if(!epic_level_can_bank(ch))") < unspec.index("epic_transaction_submit(")
    teacher = _flat(source("classes/epic_skills.c").read_text())
    assert "epics_cost=epic_skill_cost_multiplier()*(int)(cost_mod*pReward->points_cost);" in teacher
    refund = _flat(_definition("world/epic.c", "void refund_epic_skills(P_char ch)"))
    assert "points_cost*epic_skill_refund_multiplier();" in refund
    assert "points_cost*3" not in refund


def test_below_the_bank_level_epic_points_are_kept_but_frozen() -> None:
    # Owner's call, 21 Nov 2026: losing level 56 keeps the epic points, but they
    # can't be spent until the character is back at 56 (this replaced forfeiting them).
    helpers = "\n".join(_definition("world/epic.c", signature) for signature in (
        "bool epic_level_can_spend(P_char ch)",
        "bool epic_reason_is_spend(epic_reason_type reason)",
        "void epic_notify_frozen(P_char ch, critical_source_site site)",
        "void epic_report_spend_failure(P_char ch)",
    ))
    _compile_and_run(r"""
#include "core/prototypes.h"
#include "core/utils.h"
#include "world/epic_bank.h"
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <string>
static std::string said;
static int logged = 0;
int epic_bank_min_level() { return 56; }
bool epic_level_can_bank(P_char ch) { return GET_LEVEL(ch) >= 56; }
void send_to_char(const char *text, P_char) { said = text; }
void send_to_char_f(P_char, const char *format, ...) {
    char buf[512];
    va_list args;
    va_start(args, format);
    vsnprintf(buf, sizeof(buf), format, args);
    va_end(args);
    said = buf;
}
void epiclog(int, const char *, ...) { ++logged; }
""" + helpers + r"""
static void character(char_data &ch, pc_only_data &pc, int level, int64_t epics) {
    ch = char_data{};
    pc = pc_only_data{};
    ch.only.pc = &pc;
    ch.player.level = level;
    pc.epics = epics;
}
int main() {
    char_data ch{};
    pc_only_data pc{};
    // Who can spend: 56 and up, and immortals; not a mortal below 56.
    character(ch, pc, 55, 12500);
    if (epic_level_can_spend(&ch)) return 1;
    character(ch, pc, 56, 12500);
    if (!epic_level_can_spend(&ch)) return 2;
    character(ch, pc, 58, 900);
    if (!epic_level_can_spend(&ch)) return 3;
    if (!epic_level_can_spend(nullptr)) return 4;
    // What counts as spending: purchases and fees, not awards, refunds or admin work.
    for (epic_reason_type r : { epic_reason_type::store_purchase, epic_reason_type::tradeskill_reset,
                                epic_reason_type::specialization_purchase,
                                epic_reason_type::epic_skill_purchase,
                                epic_reason_type::ascend_descend, epic_reason_type::ship_purchase })
        if (!epic_reason_is_spend(r)) return 5;
    for (epic_reason_type r : { epic_reason_type::epic_skill_refund, epic_reason_type::level_purchase,
                                epic_reason_type::admin_adjustment, epic_reason_type::nexus_award,
                                epic_reason_type::bank_level_forfeit, epic_reason_type::unknown })
        if (epic_reason_is_spend(r)) return 6;
    // The notice: the balance is untouched; only a level loss is logged.
    character(ch, pc, 55, 12500);
    said.clear();
    epic_notify_frozen(&ch, critical_source_site::combat);
    if (pc.epics != 12500 || said.find("12500 epic points are frozen") == std::string::npos ||
        said.find("level 56") == std::string::npos || logged != 1)
        return 7;
    epic_notify_frozen(&ch, critical_source_site::login);
    if (pc.epics != 12500 || logged != 1) return 8;
    character(ch, pc, 56, 12500);
    said.clear();
    epic_notify_frozen(&ch, critical_source_site::combat);
    if (!said.empty()) return 9;
    character(ch, pc, 55, 0);
    epic_notify_frozen(&ch, critical_source_site::combat);
    if (!said.empty()) return 10;
    epic_notify_frozen(nullptr, critical_source_site::combat);
    // A refused purchase says why.
    character(ch, pc, 55, 12500);
    epic_report_spend_failure(&ch);
    if (said.find("frozen until you reach level 56") == std::string::npos) return 11;
    character(ch, pc, 56, 12500);
    epic_report_spend_failure(&ch);
    if (said.find("busy") == std::string::npos) return 12;
    std::puts("bank level: below 56 the points are kept and frozen; 56 and immortals spend");
    return 0;
}
""")
    # The ledger refuses a spend below the bank level, before queuing anything.
    submit = _flat(_definition("world/epic_transaction.c", "bool epic_transaction_submit_identified("))
    gate = "if(delta<0&&epic_reason_is_spend(reason)&&!epic_level_can_spend(character))returnfalse;"
    assert gate in submit
    assert submit.index(gate) < submit.index("critical_command_coordinator_submit(")
    # Nothing forfeits any more: the level loss and login only tell the player.
    lose = _flat(_definition("world/limits.c", "static void lose_level_impl("))
    assert ("if(previous_level>=epic_bank_min_level()&&GET_LEVEL(ch)<epic_bank_min_level())"
            "epic_notify_frozen(ch,") in lose
    assert lose.index("ch->player.level=MAX(1,ch->player.level-1);") < lose.index("epic_notify_frozen(")
    nanny = _flat(source("account/nanny.c").read_text())
    ready = nanny.index("epic_transaction_player_ready(ch);")
    assert ready < nanny.index("epic_notify_frozen(ch,critical_source_site::login);", ready)
    assert nanny.index("advance_to_level(ch,56);") < ready, "CHAOS characters reach 56 first"
    for name in ("world/epic.c", "world/limits.c", "account/nanny.c"):
        assert "epic_forfeit_below_bank" not in source(name).read_text(), name
    # Every spend site reports a refusal through epic_report_spend_failure().
    for name, count in (("classes/epic_skills.c", 1), ("classes/salchemist.c", 1),
                        ("classes/specializations.c", 1), ("cmd/actinf.c", 1),
                        ("cmd/actoth.c", 3), ("economy/nexus_stones.c", 1),
                        ("economy/tradeskill.c", 2), ("ships/ship_shop.c", 1)):
        assert source(name).read_text().count("epic_report_spend_failure(") == count, name
    # score shows a frozen balance.
    assert "epic_level_can_spend(ch)" in _flat(source("cmd/actinf.c").read_text())
    codec = source("world/epic_command.c").read_text()
    assert "reason <= epic_reason_type::bank_level_forfeit;" in codec


# ------------------------------------------------------------------ artifact feeding

FEED_DEFAULTS = {
    "zone": ("typeMod.zone", 0.02), "quest": ("typeMod.quest", 0.02),
    "elitemob": ("typeMod.eliteMob", 0.01), "randomzone": ("typeMod.randomZone", 0.04),
    "nexus": ("typeMod.nexusStone", 0.067), "boon": ("typeMod.boon", 0.033),
    "randommob": ("typeMod.randomMob", 0.01), "strahd": ("typeMod.strahdMe", 0.02),
    "pvp": ("typeMod.pvp", 7.2), "pvpship": ("typeMod.pvpShip", 0.5),
}


def test_feed_defaults_match_the_shipped_properties() -> None:
    rates = source("guild/artifact_feed_rates.c").read_text()
    for name, (suffix, value) in FEED_DEFAULTS.items():
        key = f"artifact.feeding.epic.{suffix}"
        entry = re.search(r'\{\s*"' + name + r'",[^}]*"' + re.escape(key) + r'",\s*([0-9.]+)', rates)
        assert entry and float(entry.group(1)) == value, name
        assert abs(PROPS[key] - value) < 0.0005, key
    assert PROPS["artifact.feeding.epic.point.seconds"] == 1200
    assert PROPS["artifact.feeding.nonPvp.ceilingHours"] == 72


def test_feed_rate_lookup_clamps_and_maps_award_types() -> None:
    _compile_and_run(r'''
#include "core/prototypes.h"
#include "guild/artifact_feed_rates.h"
#include "world/db.h"
#include "world/epic.h"
#include <cmath>
#include <cstdio>
#include <map>
#include <string>
static std::map<std::string, float> props;
float get_property(const char *key, double fallback, bool) {
    const auto found = props.find(key);
    return found == props.end() ? static_cast<float>(fallback) : found->second;
}
static bool near(double a, double b) { return std::fabs(a - b) < 1e-6; }
int main() {
    if (!near(artifact_feed_type_mod(EPIC_ZONE), 0.02) || !near(artifact_feed_type_mod(EPIC_PVP), 7.2) ||
        !near(artifact_feed_type_mod(EPIC_RANDOMMOB), 0.01) || !near(artifact_feed_type_mod(EPIC_STRAHDME), 0.02) ||
        artifact_feed_type_mod(EPIC_BOTTLE) != 0.0)
        return 1;
    if (artifact_feed_point_seconds() != 1200 || artifact_feed_nonpvp_ceiling_seconds() != 72 * 3600)
        return 2;
    props["artifact.feeding.epic.typeMod.zone"] = 99;
    props["artifact.feeding.epic.typeMod.boon"] = -3;
    props["artifact.feeding.nonPvp.ceilingHours"] = 1000;
    if (!near(artifact_feed_type_mod(EPIC_ZONE), 50.0) || artifact_feed_type_mod(EPIC_BOON) != 0.0 ||
        artifact_feed_nonpvp_ceiling_seconds() != static_cast<int64_t>(ARTIFACT_BLOOD_DAYS) * 24 * 3600)
        return 3;
    if (!artifact_feed_setting_find("ZONE") || !artifact_feed_setting_find("ceiling") ||
        !artifact_feed_setting_find("point") || artifact_feed_setting_find("nope") ||
        artifact_feed_setting_find(nullptr))
        return 4;
    if (!artifact_feed_is_pvp(EPIC_PVP) || !artifact_feed_is_pvp(EPIC_SHIP_PVP) || artifact_feed_is_pvp(EPIC_ZONE))
        return 5;
    std::puts("artifact feed rates: defaults, clamps, lookup and award types passed");
    return 0;
}
''', (source("guild/artifact_feed_rates.c"),))


def test_non_pvp_feeds_stop_at_the_ceiling_and_never_lower_a_timer() -> None:
    state = _flat(source("guild/artifact_guild_state.c").read_text())
    assert ("(artifact_feed_is_pvp(epic_type)?static_cast<int64_t>(ARTIFACT_BLOOD_DAYS)*SECS_PER_REAL_DAY:"
            "artifact_feed_nonpvp_ceiling_seconds())") in state
    assert "if(target>maximum)target=std::max(state->second.timer,maximum);" in state
    assert "if(target<=state->second.timer)continue;" in state
    seconds = _flat(_definition("guild/artifact_guild_state.c", "int artifact_feed_seconds("))
    assert "artifact_feed_type_mod(epic_type)" in seconds
    assert "artifact_feed_point_seconds()" in seconds


def test_artifeed_command_is_registered_and_forger_gated() -> None:
    interp = source("cmd/interp.c").read_text()
    assert '\t"dummy",\n\t"artifeed",\n\t"\\n" /* MAX_CMD = 866' in interp
    assert "CMD_GRT(CMD_ARTIFEED, STAT_DEAD + POS_PRONE, do_artifeed, LESSER_G);" in interp
    assert "#define CMD_ARTIFEED 865" in source("cmd/interp.h").read_text()
    assert "void do_artifeed(P_char, char *, int);" in source("core/prototypes.h").read_text()
    for module in ("guild/artifact_feed_rates.o", "guild/artifact_feed_command.o"):
        assert module in (ROOT / "src" / "Makefile").read_text()
    command = _flat(_definition("guild/artifact_feed_command.c", "void do_artifeed("))
    gate = command.index("if(GET_LEVEL(ch)<FORGER)")
    assert gate < command.index("save_setting(ch,")
    assert "value<setting->minimum||value>setting->maximum" in command
    saver = _flat(_definition("guild/artifact_feed_command.c", "bool save_setting("))
    assert "set_and_save_property(setting.property," in saver
    assert "sql_log(ch,WIZLOG," in saver
    attributes = (ROOT / "docs/lib/information/command_attributes.txt").read_text()
    assert "\nartifeed\n~\n" in attributes


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("epic levelling reform contracts passed")
