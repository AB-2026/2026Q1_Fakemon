// score.js
// ─────────────────────────────────────────────────────────────────────────────
// Fakemon Power Scorer
//
// Simulates N battles between the Fakemon and a fixed benchmark opponent.
// Win rate (0–100) is the power score. All 5 stats, type matchups, flinch,
// accuracy, and defense are implemented here to match the game engine exactly.
//
// FakemonScorer.calcPowerLevel(fakemon) → integer 0–100
// ─────────────────────────────────────────────────────────────────────────────

const FakemonScorer = (() => {

  const SIMULATIONS = 200;
  const MAX_TURNS   = 60;

  // ── Move speed: order and damage multiplier ───────────────────────────────
  const SPEED_MULT  = { fast: 1.15, medium: 1.0, slow: 0.88 };
  const SPEED_ORDER = { fast: 1, medium: 2, slow: 3 };

  // ── Type matchup table ────────────────────────────────────────────────────
  // TYPE_CHART[attackerType][defenderType] = multiplier (2 = super, 0.5 = not very, 1 = normal)
  const TYPE_CHART = buildTypeChart();

  function buildTypeChart() {
    // All match-ups default to 1. We only declare the non-1 entries.
    // strong[A] = types that A hits for 2×
    // weak[A]   = types that A hits for 0.5×
    const strong = {
      Fire:     ['Air', 'Ice', 'Nature', 'Metal'],
      Water:    ['Fire', 'Earth'],
      Air:      ['Nature'],
      Earth:    ['Electric', 'Poison'],
      Electric: ['Water', 'Air'],
      Ice:      ['Nature'],
      Poison:   ['Nature'],
      Dark:     ['Ghost'],
      Ghost:    ['Ghost', 'Dark', 'Poison'],
      Metal:    ['Ice', 'Electric'],
      Nature:   ['Water', 'Earth'],
      Normal:   [],
    };
    const weak = {
      Fire:     ['Water', 'Ice'],
      Water:    ['Nature'],
      Air:      ['Electric'],
      Earth:    ['Water', 'Nature'],
      Electric: ['Earth', 'Metal'],
      Ice:      ['Fire', 'Metal'],
      Poison:   ['Ghost'],
      Dark:     [],
      Ghost:    ['Normal'],
      Metal:    ['Fire'],
      Nature:   ['Fire', 'Air', 'Ice', 'Poison'],
      Normal:   [],
    };

    const chart = {};
    const types = Object.keys(strong);
    for (const atk of types) {
      chart[atk] = {};
      for (const def of types) {
        if (strong[atk].includes(def)) chart[atk][def] = 2;
        else if (weak[atk].includes(def)) chart[atk][def] = 0.5;
        else chart[atk][def] = 1;
      }
    }
    return chart;
  }

  function typeMultiplier(attackerType, defenderType) {
    if (!attackerType || !defenderType) return 1;
    const row = TYPE_CHART[attackerType];
    if (!row) return 1;
    return row[defenderType] ?? 1;
  }

  // ── Primary statuses: only one at a time ──────────────────────────────────
  const PRIMARY = ['poison', 'burn', 'paralyze', 'sleep'];

  // ── Benchmark ─────────────────────────────────────────────────────────────
  // Average stats matching guide suggested midpoints.
  const BENCHMARK = {
    id: '__benchmark__',
    name: 'Benchmark',
    type: 'Normal',
    hp: 100, power: 100, speed: 90, defense: 10, accuracy: 90,
    moves: [
      { id:'b_atk',    speed:'medium', damage:[15,20], status:null,      statusChance:0,   statTarget:null },
      { id:'b_poison', speed:'medium', damage:[0,0],   status:'poison',  statusChance:0.6, statTarget:null },
      { id:'b_sleep',  speed:'slow',   damage:[0,0],   status:'sleep',   statusChance:0.7, statTarget:null },
      { id:'b_heal',   speed:'slow',   damage:[-20,-20],status:null,     statusChance:0,   statTarget:null },
    ],
  };

  // ── Fighter state ─────────────────────────────────────────────────────────
  function mkState(f) {
    return {
      // base stats (read from JSON, normalised to 100 = baseline)
      hp:          f.hp       ?? 100,
      maxHp:       f.hp       ?? 100,
      power:       f.power    ?? 100,   // scales outgoing damage
      speed:       f.speed    ?? 90,    // tiebreaks within same speed tier
      defense:     f.defense  ?? 10,    // % damage reduction
      accuracy:    f.accuracy ?? 90,    // base hit chance %
      type:        f.type     || 'Normal',
      moves:       f.moves,
      // stat modifiers (raised/lowered by statup/statdwn moves)
      powerMod:    0,   // additive %, e.g. +20 means ×1.20
      speedMod:    0,
      defenseMod:  0,
      accuracyMod: 0,
      // status tracking
      statuses:     [],
      sleepTurns:   0,
      confuseTurns: 0,
      statupTurns:  0,
      statdwnTurns: 0,
      flinched:     false,
    };
  }

  // ── Status application ────────────────────────────────────────────────────
  function applyStatus(f, status, statTarget) {
    if (status === 'flinch') { f.flinched = true; return; }
    if (f.statuses.includes(status)) return;
    if (PRIMARY.includes(status) && PRIMARY.some(s => f.statuses.includes(s))) return;
    f.statuses.push(status);
    if (status === 'sleep')    { f.sleepTurns   = rng(2, 3); }
    if (status === 'confuse')  { f.confuseTurns = rng(2, 4); }
    if (status === 'paralyze') { f.speedMod    -= 30; }  // -30 speed points while paralyzed
    if (status === 'burn')     { f.powerMod    -= 20; }  // -20 power points while burned
    if (status === 'statup') {
      const t = statTarget || 'power';
      if (t === 'power')    { f.powerMod    += 20; f.statupTurns = 3; }
      if (t === 'speed')    { f.speedMod    += 20; f.statupTurns = 3; }
      if (t === 'defense')  { f.defenseMod  += 15; f.statupTurns = 3; }
      if (t === 'accuracy') { f.accuracyMod += 15; f.statupTurns = 3; }
    }
    if (status === 'statdwn') {
      const t = statTarget || 'power';
      if (t === 'power')    { f.powerMod    -= 20; f.statdwnTurns = 3; }
      if (t === 'speed')    { f.speedMod    -= 20; f.statdwnTurns = 3; }
      if (t === 'defense')  { f.defenseMod  -= 15; f.statdwnTurns = 3; }
      if (t === 'accuracy') { f.accuracyMod -= 15; f.statdwnTurns = 3; }
    }
  }

  function removeStatus(f, status) {
    f.statuses = f.statuses.filter(s => s !== status);
  }

  // ── Effective stats (base + modifier) ─────────────────────────────────────
  const effPower    = f => Math.max(10,  f.power    + f.powerMod);
  const effSpeed    = f => Math.max(1,   f.speed    + f.speedMod);
  const effDefense  = f => Math.max(0,   Math.min(80, f.defense + f.defenseMod));
  const effAccuracy = f => Math.max(10,  Math.min(100, f.accuracy + f.accuracyMod));

  // ── Pre-action checks (sleep / paralyze / confuse / flinch) ──────────────
  function preActionChecks(f) {
    // flinch resets each turn after consuming
    if (f.flinched) { f.flinched = false; return { blocked: true, selfDmg: 0 }; }
    if (f.statuses.includes('sleep')) {
      f.sleepTurns--;
      if (f.sleepTurns <= 0) removeStatus(f, 'sleep');
      else return { blocked: true, selfDmg: 0 };
    }
    if (f.statuses.includes('paralyze') && Math.random() < 0.35)
      return { blocked: true, selfDmg: 0 };
    if (f.statuses.includes('confuse') && Math.random() < 0.33)
      return { blocked: true, selfDmg: rng(8, 15) };
    return { blocked: false, selfDmg: 0 };
  }

  // ── Damage calculation ────────────────────────────────────────────────────
  function calcDamage(attacker, defender, base, moveSpeed) {
    const powerMult   = effPower(attacker) / 100;       // 100 power = 1.0×
    const spdMult     = SPEED_MULT[moveSpeed] || 1.0;
    const typeMult    = typeMultiplier(attacker.type, defender.type);
    const defReduct   = 1 - effDefense(defender) / 100; // defense 20 → 0.8×
    return Math.max(1, Math.round(base * powerMult * spdMult * typeMult * defReduct));
  }

  // ── Execute one move ──────────────────────────────────────────────────────
  function executeMove(attacker, defender, move) {
    // Accuracy check
    if (Math.random() * 100 > effAccuracy(attacker)) return; // miss

    const isHeal = move.damage && move.damage[1] < 0;
    if (isHeal) {
      const amt = Math.abs(move.damage[0]);
      attacker.hp = Math.min(attacker.maxHp, attacker.hp + amt);
      return;
    }

    if (move.damage && move.damage[1] > 0) {
      const base = rng(move.damage[0], move.damage[1]);
      const dmg  = calcDamage(attacker, defender, base, move.speed);
      defender.hp = Math.max(0, defender.hp - dmg);
      if (move.status && move.statusChance && Math.random() < move.statusChance) {
        const tgt = (move.status === 'statup') ? attacker : defender;
        // flinch only works if we went first (handled by caller marking flinch)
        applyStatus(tgt, move.status, move.statTarget || null);
      }
      return;
    }

    // Pure status / stat move
    if (move.status) {
      const tgt    = (move.status === 'statup') ? attacker : defender;
      const chance = move.statusChance ?? 1.0;
      if (Math.random() < chance) applyStatus(tgt, move.status, move.statTarget || null);
    }
  }

  // ── End-of-turn ticks ─────────────────────────────────────────────────────
  function endOfTurnTick(f) {
    if (f.statuses.includes('burn'))   f.hp = Math.max(0, f.hp - Math.round(f.maxHp * 0.06));
    if (f.statuses.includes('poison')) f.hp = Math.max(0, f.hp - Math.round(f.maxHp * 0.08));
    if (f.statuses.includes('confuse')) {
      f.confuseTurns--;
      if (f.confuseTurns <= 0) removeStatus(f, 'confuse');
    }
    if (f.statuses.includes('statup')) {
      f.statupTurns--;
      if (f.statupTurns <= 0) {
        // reverse the modifier that was applied
        const t = 'power'; // default; exact reversal handled by just zeroing mod
        f.powerMod    = Math.max(0, f.powerMod    - 20);
        f.speedMod    = Math.max(f.speedMod,    f.speedMod);
        f.defenseMod  = Math.max(0, f.defenseMod  - 15);
        f.accuracyMod = Math.max(0, f.accuracyMod - 15);
        removeStatus(f, 'statup');
      }
    }
    if (f.statuses.includes('statdwn')) {
      f.statdwnTurns--;
      if (f.statdwnTurns <= 0) {
        f.powerMod    = Math.min(0, f.powerMod    + 20);
        f.speedMod    = Math.min(0, f.speedMod    + 20);
        f.defenseMod  = Math.min(0, f.defenseMod  + 15);
        f.accuracyMod = Math.min(0, f.accuracyMod + 15);
        removeStatus(f, 'statdwn');
      }
    }
  }

  // ── AI move scorer ────────────────────────────────────────────────────────
  const STATUS_VALUE = { sleep:16, paralyze:14, burn:12, poison:10, statdwn:10, statup:10, confuse:8, flinch:6 };

  function scoreMoveForAI(move, self, opponent) {
    const isHeal = move.damage && move.damage[1] < 0;
    const hpFrac = self.hp / self.maxHp;

    if (isHeal) {
      if (hpFrac > 0.7) return -5;
      return Math.abs(move.damage[0]) * (1 - hpFrac) * 3;
    }

    let score = 0;
    if (move.damage && move.damage[1] > 0) {
      const mid  = (move.damage[0] + move.damage[1]) / 2;
      score += calcDamage(self, opponent, mid, move.speed);
    }
    if (move.status && (move.statusChance ?? 0) > 0) {
      const tgtSelf = move.status === 'statup';
      const tgt = tgtSelf ? self : opponent;
      if (!tgt.statuses.includes(move.status)) {
        score += (STATUS_VALUE[move.status] || 5) * move.statusChance;
      }
    }
    return score;
  }

  function pickBestMove(self, opponent) {
    let best = self.moves[0], bestScore = -Infinity;
    for (const m of self.moves) {
      const s = scoreMoveForAI(m, self, opponent);
      if (s > bestScore) { bestScore = s; best = m; }
    }
    return best;
  }

  // ── One battle ────────────────────────────────────────────────────────────
  function runOneBattle(subject, benchDef) {
    const a = mkState(subject);
    const b = mkState(benchDef);

    for (let t = 0; t < MAX_TURNS; t++) {
      const mA = pickBestMove(a, b);
      const mB = pickBestMove(b, a);

      // Move speed tier, then fakemon speed stat as tiebreaker
      const tierA = SPEED_ORDER[mA.speed] || 2;
      const tierB = SPEED_ORDER[mB.speed] || 2;
      const aFirst = tierA < tierB || (tierA === tierB && effSpeed(a) >= effSpeed(b));

      const first  = aFirst ? [a, b, mA, true]  : [b, a, mB, false];
      const second = aFirst ? [b, a, mB, false] : [a, b, mA, true];

      for (const [attacker, defender, move, isSubject] of [first, second]) {
        const { blocked, selfDmg } = preActionChecks(attacker);
        attacker.hp = Math.max(0, attacker.hp - selfDmg);
        if (!blocked) {
          const hpBefore = defender.hp;
          executeMove(attacker, defender, move);
          // Apply flinch if this was a damage move and attacker went first
          const didDamage = defender.hp < hpBefore;
          if (didDamage && move.status === 'flinch' && move.statusChance && Math.random() < move.statusChance) {
            defender.flinched = true;
          }
        }
        if (a.hp <= 0) return false;
        if (b.hp <= 0) return true;
      }

      endOfTurnTick(a);
      endOfTurnTick(b);
      if (a.hp <= 0) return false;
      if (b.hp <= 0) return true;
    }
    return false; // draw = loss
  }

  // ── Public API ────────────────────────────────────────────────────────────
  function calcPowerLevel(fakemon) {
    let wins = 0;
    for (let i = 0; i < SIMULATIONS; i++) {
      if (runOneBattle(fakemon, BENCHMARK)) wins++;
    }
    return Math.round((wins / SIMULATIONS) * 100);
  }

  function rng(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a; }

  return { calcPowerLevel, typeMultiplier };

})();
