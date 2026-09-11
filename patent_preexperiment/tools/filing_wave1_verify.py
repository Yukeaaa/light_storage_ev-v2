# -*- coding: utf-8 -*-
"""提交源文件验收：权项保真度 / 结构完整性 / 内部信息残留。"""
import re, pathlib

BASE = pathlib.Path(r"D:/JobWorkspaces/light_storage_ev-v2/patent_preexperiment/reports")
OUT = BASE / "patent_filing_wave1"


def norm(s):
    s = s.replace("**", "")
    s = re.sub(r"【[a-e]】", "", s)
    s = s.replace("……", "")
    s = re.sub(r"\s+", "", s)
    return s


def parse_claims(md_text, prefix):
    """从提交源文件/权威稿中解析权项：返回 {编号: 归一化正文}"""
    lines = md_text.splitlines()
    claims, cur_n, buf = {}, None, []
    done = False
    for ln in lines:
        if done:
            break
        m = re.match(r"^(\d+)\.\s+(.*)$", ln)
        if m and cur_n is None:
            cur_n = int(m.group(1))
            buf = [m.group(2)]
            continue
        if m and cur_n is not None and int(m.group(1)) == cur_n + 1:
            claims[cur_n] = "\n".join(buf)
            cur_n = int(m.group(1))
            buf = [m.group(2)]
            continue
        if cur_n is not None:
            if re.match(r"^##\s", ln):
                claims[cur_n] = "\n".join(buf)
                cur_n = None
                buf = []
                done = True
                continue
            buf.append(ln)
    if cur_n is not None:
        claims[cur_n] = "\n".join(buf)
    # 去掉 "根据权利要求 1 所述的…，其特征在于，" 由权威稿侧统一补
    return claims


def extract_src_claims(text, dep_prefix, border):
    """从权威稿解析：独立权取 ```text 块；从属权取 '……其特征在于，' 行。"""
    res = {}
    # 裁决：先按 '**权 N（' 分块
    parts = re.split(r"\*\*权\s*(\d+)[^*]*\*\*", text)
    # parts: [pre, n1, body1, n2, body2, ...]
    for i in range(1, len(parts), 2):
        n = int(parts[i])
        body = parts[i + 1]
        b = re.split(r"\n\s*>|\n---|\n##\s", body, maxsplit=1)[0]
        m = re.search(r"……其特征在于，(.*)", b, re.S)
        if m:
            res[n] = dep_prefix + "其特征在于，" + m.group(1)
    return res


def code_block(text, marker):
    seg = text.split(marker, 1)[1]
    m = re.search(r"```text\n(.*?)```", seg, re.S)
    return re.sub(r"^\s*\d+\.\s*", "", m.group(1), count=1)


A16 = (BASE / "patent_definition/16_A权利要求语言v2定稿_反馈对象闭合.md").read_text(encoding="utf-8")
C12 = (BASE / "patent_pool/C_控制资格状态机_Claim_Draft_v1.2.md").read_text(encoding="utf-8")
Af = (OUT / "A_正式提交源文件_V1.md").read_text(encoding="utf-8")
Cf = (OUT / "C_正式提交源文件_V1.md").read_text(encoding="utf-8")

# ---- A 权威稿权项 ----
A_src = {}
b1 = code_block(A16, "## 2. 权利要求 1")
A_src[1] = b1
A_src.update(extract_src_claims(A16, "根据权利要求 1 所述的站级功率控制方法，", "## 3."))
b12 = code_block(A16, "## 4. 权利要求 12")
A_src[12] = b12

# ---- C 权威稿权项 ----
C_src = {}
C_src[1] = code_block(C12, "## 1. 权利要求 1")
C_src.update(extract_src_claims(C12, "根据权利要求 1 所述的设备控制参与资格的控制方法，", "## 3."))
C_src[10] = code_block(C12, "## 3. 权利要求 10")

A_sub = parse_claims(Af, None)
C_sub = parse_claims(Cf, None)

print("=" * 60)
print("【验收 1】权项保真度（归一化后必须完全一致）")
print("=" * 60)


def cmp(name, src, sub, expect_n):
    ok = True
    for n in range(1, expect_n + 1):
        if n not in src:
            print(f"  {name} 权{n}: 权威稿未解析到 -> 跳过"); continue
        if n not in sub:
            print(f"  {name} 权{n}: 提交稿缺失  ❌"); ok = False; continue
        a, b = norm(src[n]), norm(sub[n])
        if a == b:
            print(f"  {name} 权{n}: 一致 ✅  ({len(a)} 字符)")
        else:
            ok = False
            print(f"  {name} 权{n}: 不一致 ❌")
            for i in range(min(len(a), len(b))):
                if a[i] != b[i]:
                    print(f"     首处差异 @{i}: 权威='{a[max(0,i-25):i+25]}' vs 提交='{b[max(0,i-25):i+25]}'")
                    break
            else:
                print(f"     长度不同：权威 {len(a)} vs 提交 {len(b)}")
    return ok


okA = cmp("A", A_src, A_sub, 12)
okC = cmp("C", C_src, C_sub, 10)

print()
print("=" * 60)
print("【验收 2】结构完整性")
print("=" * 60)
need = ["## 权利要求书", "技术领域", "背景技术", "发明内容", "附图说明", "具体实施方式",
        "## 说明书摘要", "## 说明书附图"]
for name, f in (("A", Af), ("C", Cf)):
    miss = [k for k in need if k not in f]
    print(f"  {name}: " + ("全部齐备 ✅" if not miss else f"缺失 {miss} ❌"))

print()
print("=" * 60)
print("【验收 3】内部信息残留（必须全部为 0）")
print("=" * 60)
KEYS = ["§", "起草注记", "退守位", "反审", "红线", "自检", "Open item", "PASS", "STOP",
        "UNVALIDATED", "RD-", "M5BAT", "OpenCEM", "lit45", "另一申请", "证据档",
        "【a】", "【b】", "【c】", "【d】", "【e】", "状态机", "附录 A", "附录 B", "待决事项",
        ]
for name, f in (("A", Af), ("C", Cf)):
    bad = []
    for k in KEYS:
        c = len(re.findall(re.escape(k), f))
        if c:
            bad.append(f"{k}={c}")
    print(f"  {name}: " + ("全 0 ✅" if not bad else "残留 -> " + ", ".join(bad)))

print()
print("=" * 60)
print("【补充】交叉术语越界（A 稿不得含 C 状态对象；C 稿不得含 A 状态对象）")
print("=" * 60)
C_ONLY = ["控制参与资格", "允许控制动作范围", "可控资源集合", "控制资源子集", "恢复判据"]
A_ONLY = ["方向化可用能力状态", "能力边界", "执行偏差", "可承接贡献", "功率修正量", "承接资源", "功率控制要求"]
for name, f, keys in (("A", Af, C_ONLY), ("C", Cf, A_ONLY)):
    hits = []
    body = f.split("## 说明书摘要")[0]
    for k in keys:
        c = len(re.findall(re.escape(k), body))
        if c:
            hits.append(f"{k}={c}")
    print(f"  {name} 正文(含权项+说明书): " + ("无越界 ✅" if not hits else "命中 -> " + ", ".join(hits)))

print()
print("=" * 60)
print("【验收 4】内部交叉引用与内部评审语言残留")
print("=" * 60)
for name, f in (("A", Af), ("C", Cf)):
    hits = []
    for pat in [r"第\s*\d+\s*节", r"删除本节", r"本节内容", r"本说明书", r"权\s*\d+\s*的", r"退守位"]:
        c = len(re.findall(pat, f))
        if c:
            hits.append(f"{pat}={c}")
    print(f"  {name}: " + ("无残留 ✅" if not hits else "命中 -> " + ", ".join(hits)))

print()
print("=" * 60)
print("【验收 5】说明书摘要字符数（含标点，受理上限 300）")
print("=" * 60)
for name, f in (("A", Af), ("C", Cf)):
    seg = f.split("## 说明书摘要")[1].split("## 说明书附图")[0]
    n = len(re.sub(r"\s", "", seg))
    print(f"  {name}: {n} 字 -> " + ("合规 ✅" if n <= 300 else "超限 ❌"))


print()
print("结论: 权项保真 A=%s C=%s" % ("PASS" if okA else "FAIL", "PASS" if okC else "FAIL"))
