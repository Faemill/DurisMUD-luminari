#ifndef EPIC_BANK_H
#define EPIC_BANK_H

#include "core/structs.h"
#include "persistence/critical_command.h"
#include "world/epic_command.h"

/*
 * Epic points are banked only from epic.bank.minLevel (default 56). From
 * epic.gain.minLevel up to it, epic awards still feed artifacts and guild
 * prestige from their full amount but are paid as experience:
 *
 *   exp = epics x epic.convert.exp.<level>
 *
 * Kept apart from world/epic.h, whose bytes the epic zone seed manifest hashes.
 */

/** The lowest level that keeps epic points. */
int epic_bank_min_level();

/** True when the character's awards are banked as epic points. */
bool epic_level_can_bank(P_char ch);

/** Experience paid for one epic point earned at the given level below the bank level. */
int epic_conversion_exp_per_epic(int level);

/**
 * Pays an award earned below the bank level as experience. The caller has already
 * fed artifacts and guild prestige from the full epic amount.
 */
void epic_pay_converted_award(P_char ch, int type, int data, int amount);

/**
 * Epic points are spent only from the bank level. A character below it -- one who
 * lost level 56 to a death, or who held points from before the reform -- keeps its
 * balance, frozen: nothing it buys with epic points goes through until it is back at
 * the bank level (owner's call, 21 Nov 2026; this replaced forfeiting the balance).
 * True for an immortal and for a character at or above the bank level.
 */
bool epic_level_can_spend(P_char ch);

/**
 * True for the ledger reasons that spend a player's points on something: store and
 * nexus purchases, tradeskill resets, specialization and ascend/descend fees, epic
 * skills and ship hulls. Not awards, refunds, admin adjustments or a stone's level
 * purchase (epic.forLevel is 0 for 51-56 with the reform, and a non-zero price must
 * not leave a character unable to level).
 */
bool epic_reason_is_spend(epic_reason_type reason);

/**
 * Tells a character below the bank level that its balance is frozen: at the level
 * loss that takes it below (site combat or command) and at login. The balance is not
 * touched. Does nothing for an immortal, at or above the bank level, or with no
 * points.
 */
void epic_notify_frozen(P_char ch, critical_source_site site);

/**
 * The message for an epic purchase that could not be queued: the frozen-balance
 * notice when the character is below the bank level (the ledger refuses the spend),
 * else the usual "service is busy".
 */
void epic_report_spend_failure(P_char ch);

/** The epic skill price multiplier, epic.skill.costMultiplier (default 5). */
int epic_skill_cost_multiplier();

/** The epic skill refund multiplier, epic.skill.refundMultiplier (default 3). */
int epic_skill_refund_multiplier();

#endif
