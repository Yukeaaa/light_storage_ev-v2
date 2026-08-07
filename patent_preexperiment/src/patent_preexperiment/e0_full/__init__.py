"""E0-Full 包：全量输入 manifest、数据质量审计、baseline 与连接时间审计。

依据：V2.1 §10；审查结论7 §5；审查结论9。

子模块：
- input_audit：独立全量扫描（sha256/gzip/read/覆盖/短文件/重复/倒序/严重缺口）；
  connectionTime 只审计不切分。
- baseline：e0_full_baseline.json 组装（code_sha、manifest_hashes、
  runtime_versions、output_manifest）。
"""
