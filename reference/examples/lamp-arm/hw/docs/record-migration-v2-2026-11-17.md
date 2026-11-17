# Record migration to record version 2

Date: 2026-11-17. Command: cad-record `migrate.py --apply`. Source: record version 1 (product.yaml without record_version).

The migration added the blocks record version 2 requires. Every new value is `unknown` and names an open
question in requirements.yaml. Nothing was approved, and no process, material, capability, criterion or
certification was inferred. The legacy `material`, `process`, `build_volume`, `min_wall_mm` and drawing fields
are unchanged: they stay declarations and diagnostic heuristics, never sourced grades, allowables or calibrated
accuracy. Answer the questions, record sources and decisions, then rebuild and recheck.

## Files changed

- `hw/requirements.yaml` (modify): adds preferences, assumptions, open_questions (27 open questions)
- `hw/parts/LMP-0001/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-012)
- `hw/parts/LMP-0002/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-013)
- `hw/parts/LMP-0003/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-014)
- `hw/parts/LMP-0004/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-015)
- `hw/parts/LMP-0005/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-016)
- `hw/parts/LMP-0006/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-017)
- `hw/parts/LMP-0007/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-018)
- `hw/parts/LMP-0008/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-019)
- `hw/parts/LMP-0009/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-020)
- `hw/parts/LMP-0010/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-021)
- `hw/parts/LMP-0011/part.yaml` (modify): adds intent: functions, material_profile, service, critical_surfaces and route unknown (Q-022)
- `hw/interfaces.yaml` (modify): adds functional (critical and functions unknown) to IF-001, IF-002, IF-003, IF-004, IF-005
- `hw/assembly.yaml` (modify): moves drawing.operations (9 operations) to top-level operations, unchanged
- `hw/manufacturing/capabilities.yaml` (create): creates it with nothing recorded
- `hw/manufacturing/materials.yaml` (create): creates it with nothing recorded
- `hw/manufacturing/selection.yaml` (create): creates it with nothing recorded
- `hw/product.yaml` (modify): sets record_version 2; adds use_case: every field unknown (Q-001 to Q-011)

## Now explicitly unknown

- use case: service class, purpose, users, environment, loads, motion, accuracy, consequences, logistics, capability, release scope and evidence policy (Q-001 to Q-011)
- capabilities, material profiles and selection: none recorded (hw/manufacturing/)
- LMP-0001: functions, material profile, service, critical surfaces and route (Q-012)
- LMP-0002: functions, material profile, service, critical surfaces and route (Q-013)
- LMP-0003: functions, material profile, service, critical surfaces and route (Q-014)
- LMP-0004: functions, material profile, service, critical surfaces and route (Q-015)
- LMP-0005: functions, material profile, service, critical surfaces and route (Q-016)
- LMP-0006: functions, material profile, service, critical surfaces and route (Q-017)
- LMP-0007: functions, material profile, service, critical surfaces and route (Q-018)
- LMP-0008: functions, material profile, service, critical surfaces and route (Q-019)
- LMP-0009: functions, material profile, service, critical surfaces and route (Q-020)
- LMP-0010: functions, material profile, service, critical surfaces and route (Q-021)
- LMP-0011: functions, material profile, service, critical surfaces and route (Q-022)
- IF-001: criticality and functions (Q-023)
- IF-002: criticality and functions (Q-024)
- IF-003: criticality and functions (Q-025)
- IF-004: criticality and functions (Q-026)
- IF-005: criticality and functions (Q-027)

## Open questions

| Id | Question |
|---|---|
| Q-001 | Which service class applies: appearance or concept model, fit or assembly prototype, functional demonstration with limited loads and supervised operation, working prototype, production or end-use product, or safety-critical, regulated or high-consequence application? |
| Q-002 | What must the product do, and who uses it? |
| Q-003 | What operating temperature range and heat sources apply? |
| Q-004 | What moisture, chemical, UV and corrosion exposure applies? |
| Q-005 | Which loads act on it: magnitude, direction, static or sustained, cyclic, impact and vibration? |
| Q-006 | Which motions occur: speed, range, duty cycle, friction, wear and expected service life? |
| Q-007 | What accuracy, repeatability, surface finish and dimensional stability are required? |
| Q-008 | What are the consequences of failure, the forbidden outcomes, the applicable standards or safety requirements, the supervision and the approving authority? |
| Q-009 | What quantity, budget, lead time, maintenance and repair needs apply? |
| Q-010 | Which equipment and operators are available, and is outsourcing acceptable? |
| Q-011 | What may a release claim: its purpose, operating limits, exclusions and the evidence each requirement needs? |
| Q-012 | LMP-0001 (Base plate and pivot boss): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material PETG and process fdm; they stay declarations, not evidence. |
| Q-013 | LMP-0002 (Lower link): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Aluminum 6061-T6 and process cnc; they stay declarations, not evidence. |
| Q-014 | LMP-0003 (Upper link): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Aluminum 6061-T6 and process cnc; they stay declarations, not evidence. |
| Q-015 | LMP-0004 (Lamp head housing): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material PETG and process fdm; they stay declarations, not evidence. |
| Q-016 | LMP-0005 (M5 x 30 shoulder pin): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Stainless steel A2 and process cnc; they stay declarations, not evidence. |
| Q-017 | LMP-0006 (M5 x 25 shoulder pin): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Stainless steel A2 and process cnc; they stay declarations, not evidence. |
| Q-018 | LMP-0007 (M5 x 20 shoulder pin): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Stainless steel A2 and process cnc; they stay declarations, not evidence. |
| Q-019 | LMP-0008 (Bushing SPIROL CMPL 4 X 8 EK CL8000): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Brass C36000 and process purchased; they stay declarations, not evidence. |
| Q-020 | LMP-0009 (Bushing SPIROL CMPL 4 X 6 EK CL8100): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Brass C36000 and process purchased; they stay declarations, not evidence. |
| Q-021 | LMP-0010 (Heat-set insert QT M10x1 x 12.7 OD 12.6): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Brass and process purchased; they stay declarations, not evidence. |
| Q-022 | LMP-0011 (Retaining ring DIN 471 - 5x0.6): which functions does it serve, which loads and service conditions does it see, which material profile (family or exact grade) and which complete route (operations, capability, orientation, setups, supports, finishing and inspection) apply, and which surfaces are critical? The legacy record declares material Spring steel C60S and process purchased; they stay declarations, not evidence. |
| Q-023 | IF-001 (motion, base_sub to lower_link): is it critical, which functions does it serve, and which acceptance criteria, stack and contact evidence verify it? |
| Q-024 | IF-002 (motion, lower_link to upper_link): is it critical, which functions does it serve, and which acceptance criteria, stack and contact evidence verify it? |
| Q-025 | IF-003 (motion, upper_link to head): is it critical, which functions does it serve, and which acceptance criteria, stack and contact evidence verify it? |
| Q-026 | IF-004 (mounting, base_plate to work_surface): is it critical, which functions does it serve, and which acceptance criteria, stack and contact evidence verify it? |
| Q-027 | IF-005 (mounting, head to lampholder): is it critical, which functions does it serve, and which acceptance criteria, stack and contact evidence verify it? |

## Not touched

`model.py` files, geometry, `hw/versions/`, `hw/releases/`, check, drawing, render, motion and analysis bundles,
decisions, `bom.csv` and `verification.csv`. Sealed versions and releases stay readable by their own format and
are not re-certified; build a new version after migrating.
