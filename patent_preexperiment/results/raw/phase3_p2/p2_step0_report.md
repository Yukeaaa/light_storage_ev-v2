# P2 Step0 — K1/K2/K3 kill gates

- experiment_id：P2_v1_0_2
- protocol_version：phase3_p2_preregistration_v1.0.2
- scope：P2 Step0 kill gates（JPL train natural + 固定 Caltech replay，不挑样本）

## Step0 verdict：**`PROCEED`**

## Kill gates

- **K1（D1 mode selection）**：`PASS`（FAIL → STOP）
- **K2（D2 action set）**：`PASS`（FAIL → PROJECT_NO_GO）
  - m2=1.0、m2_disp_ok=1.0、m4=0.0、n_diff_lock_prot=2397483、n_diff_prot_normal=380716
- **K3（D3 recovery trace）**：`PASS`（FAIL → PROJECT_NO_GO）
  - JPL train natural traces：5677

## JPL train natural（current-only）

- cycles：5,993,773；sessions：13,908；runs：14,604
- info_mode 分布：{'M3_current_only': 5920880, 'M4_history_insufficient': 72893}
- boundary_mode 分布：{'conservative_fallback': 72893, 'history_protective_boundary': 5920880}
- application_state 分布：{'LOCKED': 72893, 'NORMAL': 5770835, 'PROTECTIVE': 150045}
- M1=1.0（唯一 mode 比例）、M2=1.0（n_eligible=5,993,623）、m2_cov=0.385253、M4=0.0
- M3 traces：total=14162，complete=5677，sessions=5581
- boundary_unavailable cycles：150
- release violations：0（n_protective_eligible=150,045）

## Caltech replay（mode-mechanism，单列辅助）

### natural

- cycles：3,512,166；sessions：9,327；runs：9,488
- info_mode 分布：{'M2_pilot_actual': 3460066, 'M3_current_only': 4695, 'M4_history_insufficient': 47405}
- boundary_mode 分布：{'conservative_fallback': 47405, 'history_protective_boundary': 4695, 'response_history_boundary': 3460066}
- application_state 分布：{'LOCKED': 47405, 'NORMAL': 3464695, 'PROTECTIVE': 66}
- M1=1.0（唯一 mode 比例）、M2=1.0（n_eligible=52,100）、m2_cov=0.760825、M4=0.0
- M3 traces：total=30，complete=9，sessions=9
- boundary_unavailable cycles：0
- release violations：0（n_protective_eligible=66）

- traces：total=30，complete=9（不计入 natural）

### mask_pilot

- cycles：3,512,166；sessions：9,327；runs：9,488
- info_mode 分布：{'M3_current_only': 3464761, 'M4_history_insufficient': 47405}
- boundary_mode 分布：{'conservative_fallback': 47405, 'history_protective_boundary': 3464761}
- application_state 分布：{'LOCKED': 47405, 'NORMAL': 3372734, 'PROTECTIVE': 92027}
- M1=1.0（唯一 mode 比例）、M2=1.0（n_eligible=3,511,817）、m2_cov=0.385017、M4=0.0
- M3 traces：total=9253，complete=3769，sessions=3759
- boundary_unavailable cycles：349
- release violations：0（n_protective_eligible=92,027）

- traces：total=9253，complete=3769（不计入 natural）

### truncate_history

- cycles：3,512,166；sessions：9,327；runs：9,488
- info_mode 分布：{'M4_history_insufficient': 3512166}
- boundary_mode 分布：{'conservative_fallback': 3512166}
- application_state 分布：{'LOCKED': 3512166}
- M1=1.0（唯一 mode 比例）、M2=1.0（n_eligible=3,512,166）、m2_cov=0.800012、M4=None
- M3 traces：total=0，complete=0，sessions=0
- boundary_unavailable cycles：0
- release violations：0（n_protective_eligible=0）

- traces：total=0，complete=0（不计入 natural）

### inject_capability

- cycles：3,512,166；sessions：9,327；runs：9,488
- info_mode 分布：{'M1_capability_rich': 3512166}
- boundary_mode 分布：{'capability_supported_boundary': 3512166}
- application_state 分布：{'NORMAL': 3512166}
- M1=1.0（唯一 mode 比例）、M2=None（n_eligible=0）、m2_cov=None、M4=None
- M3 traces：total=0，complete=0，sessions=0
- boundary_unavailable cycles：0
- release violations：0（n_protective_eligible=0）

- traces：total=0，complete=0（不计入 natural）
