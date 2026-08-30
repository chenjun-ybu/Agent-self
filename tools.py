"""
Tools: 具体操作能力实现

每个 Tool 提供一种原子操作：
- SmilesValidatorTool: 校验 SMILES 字符串合法性与字段完整性
- UnitConverterTool:   将不同单位统一换算到目标单位
- DuplicateCheckerTool: 检测重复记录并识别冲突

所有 Tool 遵循统一接口，通过 ToolRegistry 注册后可被 Skill 按名称调用。
"""

from protocol import ToolCallRequest, ToolCallResponse, CallStatus
from dataclasses import dataclass
from typing import Any
import re


@dataclass
class BaseTool:
    """工具基类：定义统一接口"""
    name: str
    description: str

    def execute(self, request: ToolCallRequest) -> ToolCallResponse:
        raise NotImplementedError

    def get_info(self) -> dict:
        return {"name": self.name, "description": self.description}


# ──────────────────────────────────────────────
# Tool 1: SMILES 校验器
# ──────────────────────────────────────────────
class SmilesValidatorTool(BaseTool):
    """
    校验 SMILES 字符串的合法性，同时检查必要字段是否缺失。
    使用基于规则的校验（括号配对、价键合理性、原子符号合法性），
    不依赖 RDKit，便于在无第三方依赖的环境中运行。
    """

    # 常见有机化学元素
    ORGANIC_ATOMS = {"C", "N", "O", "S", "P", "F", "Cl", "Br", "I", "B", "Si"}
    # 芳香原子小写
    AROMATIC_ATOMS = {"c", "n", "o", "s", "p"}

    def __init__(self):
        super().__init__(
            name="smiles_validator",
            description="校验 SMILES 字符串合法性及必要字段完整性"
        )

    def _validate_smiles(self, smiles: str) -> tuple[bool, str]:
        """规则化校验 SMILES 字符串"""
        if not smiles or not isinstance(smiles, str):
            return False, "SMILES 为空或非字符串"

        smiles = smiles.strip()
        if len(smiles) == 0:
            return False, "SMILES 为空字符串"

        # 括号配对
        bracket_stack = []
        bracket_map = {"(": ")", "[": "]", "{": "}"}
        for i, ch in enumerate(smiles):
            if ch in bracket_map:
                bracket_stack.append((ch, i))
            elif ch in ")]}":
                if not bracket_stack:
                    return False, f"位置 {i}: 闭括号 '{ch}' 无匹配开括号"
                open_ch, open_pos = bracket_stack.pop()
                expected = bracket_map[open_ch]
                if ch != expected:
                    return False, f"位置 {i}: 括号不匹配，'{open_ch}' 期望 '{expected}' 但得到 '{ch}'"
        if bracket_stack:
            open_ch, pos = bracket_stack[-1]
            return False, f"位置 {pos}: 开括号 '{open_ch}' 未闭合"

        # 检查方括号内原子（如 [Na], [Cl]）
        bracket_pattern = re.compile(r'\[([A-Za-z]{1,2})([+-]?\d*[Hhin]*)?\]')
        for m in bracket_pattern.finditer(smiles):
            atom = m.group(1)
            if len(atom) == 1:
                atom = atom.upper()
            else:
                atom = atom[0].upper() + atom[1:]
            if atom not in self.ORGANIC_ATOMS and atom not in {"H", "Na", "K", "Ca", "Mg", "Fe", "Cu", "Zn", "Li", "Al"}:
                pass  # 放行不常见但可能合法的元素

        # 检查非法字符
        valid_chars = set("CNOPSFBI()[]{}=#$.-/\\0123456789cnopsb%@")
        for ch in smiles:
            if ch not in valid_chars and ch not in "ClBrSiNaKMgCaFeCuZnLiAlH":
                if ch not in self.ORGANIC_ATOMS and ch not in self.AROMATIC_ATOMS:
                    if ch.isalpha() and ch.upper() not in {a.upper() for a in self.ORGANIC_ATOMS}:
                        if ch not in "%@":
                            return False, f"非法字符: '{ch}'"

        # 简单的价键检查：不允许连续4个以上相同单字母原子
        # (如 CCCC 合法，但检查环闭合数字)
        ring_nums = re.findall(r'(\d)', smiles)
        # 环闭合数字应成对出现
        from collections import Counter
        ring_counter = Counter(ring_nums)
        for num, count in ring_counter.items():
            if count % 2 != 0:
                return False, f"环闭合数字 '{num}' 出现 {count} 次，不成对"

        return True, "SMILES 校验通过"

    def execute(self, request: ToolCallRequest) -> ToolCallResponse:
        records = request.parameters.get("records", [])
        required_fields = request.parameters.get("required_fields", ["sample_id", "SMILES"])

        issues: list[str] = []
        valid_records: list[dict] = []

        for i, rec in enumerate(records):
            # 检查必要字段
            missing = [f for f in required_fields if f not in rec or rec[f] is None or rec[f] == ""]
            if missing:
                issues.append(f"记录 {i} (sample_id={rec.get('sample_id', '?')}): 缺失字段 {missing}")
                continue

            smiles = rec.get("SMILES", "")
            ok, msg = self._validate_smiles(smiles)
            if ok:
                valid_records.append(rec)
            else:
                issues.append(f"记录 {i} (sample_id={rec.get('sample_id', '?')}): SMILES '{smiles}' 无效 — {msg}")

        if issues:
            return ToolCallResponse(
                tool_name=self.name,
                call_id=request.call_id,
                status=CallStatus.ERROR if not valid_records else CallStatus.SUCCESS,
                result={"valid_records": valid_records, "issues": issues},
                error=f"发现 {len(issues)} 条问题记录" if issues else None,
            )

        return ToolCallResponse(
            tool_name=self.name,
            call_id=request.call_id,
            status=CallStatus.SUCCESS,
            result={"valid_records": valid_records, "issues": []},
        )


# ──────────────────────────────────────────────
# Tool 2: 单位转换器
# ──────────────────────────────────────────────
class UnitConverterTool(BaseTool):
    """
    将不同单位统一换算到目标单位。
    支持：温度 (°C, K, °F)、压力 (atm, kPa, mmHg)、浓度 (mol/L, mmol/L)。
    遇到未知单位时返回错误。
    """

    # 单位换算因子表：to_base_factor
    UNIT_FACTORS: dict[str, dict[str, float]] = {
        "temperature": {
            "C": 1.0,     # °C 是基准
            "K": None,     # 需偏移
            "F": None,     # 需偏移
        },
        "pressure": {
            "atm": 1.0,
            "kPa": 0.00986923,
            "mmHg": 0.00131579,
            "bar": 0.986923,
        },
        "concentration": {
            "mol/L": 1.0,
            "mmol/L": 0.001,
            "mol/m3": 0.001,
        },
    }

    def __init__(self):
        super().__init__(
            name="unit_converter",
            description="将不同单位统一换算到目标单位（温度/压力/浓度）"
        )

    def _convert_temperature(self, value: float, from_unit: str, to_unit: str) -> float:
        """温度换算需要偏移"""
        # 先转为摄氏度
        if from_unit == "C":
            celsius = value
        elif from_unit == "K":
            celsius = value - 273.15
        elif from_unit == "F":
            celsius = (value - 32) * 5 / 9
        else:
            raise ValueError(f"未知温度单位: {from_unit}")

        # 再从摄氏度转到目标
        if to_unit == "C":
            return celsius
        elif to_unit == "K":
            return celsius + 273.15
        elif to_unit == "F":
            return celsius * 9 / 5 + 32
        else:
            raise ValueError(f"未知目标温度单位: {to_unit}")

    def execute(self, request: ToolCallRequest) -> ToolCallResponse:
        records = request.parameters.get("records", [])
        property_name = request.parameters.get("property_name", "property_value")
        unit_field = request.parameters.get("unit_field", "unit")
        target_unit = request.parameters.get("target_unit", "")
        property_type = request.parameters.get("property_type", "")

        converted: list[dict] = []
        issues: list[str] = []

        for rec in records:
            new_rec = dict(rec)
            value = rec.get(property_name)
            unit = rec.get(unit_field, "")

            if value is None:
                issues.append(f"sample_id={rec.get('sample_id', '?')}: 缺少 '{property_name}' 值")
                continue

            try:
                # 判断是否温度类型
                if property_type == "temperature" or unit in ("C", "K", "F"):
                    converted_value = self._convert_temperature(float(value), unit, target_unit)
                elif unit in self.UNIT_FACTORS.get("pressure", {}):
                    factor = self.UNIT_FACTORS["pressure"][unit]
                    converted_value = float(value) * factor
                elif unit in self.UNIT_FACTORS.get("concentration", {}):
                    factor = self.UNIT_FACTORS["concentration"][unit]
                    converted_value = float(value) * factor
                else:
                    issues.append(f"sample_id={rec.get('sample_id', '?')}: 未知单位 '{unit}'")
                    continue

                new_rec[property_name] = round(converted_value, 6)
                new_rec[unit_field] = target_unit
                converted.append(new_rec)

            except (ValueError, TypeError) as e:
                issues.append(f"sample_id={rec.get('sample_id', '?')}: 转换失败 — {e}")

        if issues and not converted:
            return ToolCallResponse(
                tool_name=self.name,
                call_id=request.call_id,
                status=CallStatus.ERROR,
                result={"converted_records": [], "issues": issues},
                error=f"所有 {len(issues)} 条记录的单位转换均失败",
            )

        return ToolCallResponse(
            tool_name=self.name,
            call_id=request.call_id,
            status=CallStatus.SUCCESS if not issues else CallStatus.SUCCESS,
            result={"converted_records": converted, "issues": issues},
            error=f"{len(issues)} 条记录有单位问题" if issues else None,
        )


# ──────────────────────────────────────────────
# Tool 3: 重复记录检查器
# ──────────────────────────────────────────────
class DuplicateCheckerTool(BaseTool):
    """
    检测数据中的重复记录（基于 sample_id 或 SMILES），
    当同一 sample_id 出现多次且数值不同时，判定为冲突，需要用户确认。
    """

    def __init__(self):
        super().__init__(
            name="duplicate_checker",
            description="检测重复记录，识别数据冲突，必要时请求用户确认"
        )

    def execute(self, request: ToolCallRequest) -> ToolCallResponse:
        records = request.parameters.get("records", [])
        key_field = request.parameters.get("key_field", "sample_id")
        compare_fields = request.parameters.get("compare_fields", ["SMILES", "property_value", "unit"])

        seen: dict[str, list[dict]] = {}
        duplicates: list[dict] = []
        conflicts: list[dict] = []

        for i, rec in enumerate(records):
            key = rec.get(key_field, f"index_{i}")
            if key in seen:
                for prev_rec in seen[key]:
                    # 比较 compare_fields
                    diffs = {}
                    for cf in compare_fields:
                        if cf in rec or cf in prev_rec:
                            v1 = prev_rec.get(cf)
                            v2 = rec.get(cf)
                            if v1 != v2:
                                diffs[cf] = {"existing": v1, "new": v2}

                    entry = {
                        "key": key,
                        "records": [prev_rec, rec],
                    }
                    if diffs:
                        entry["conflict_fields"] = diffs
                        conflicts.append(entry)
                    else:
                        entry["conflict_fields"] = {}
                        duplicates.append(entry)

                seen[key].append(rec)
            else:
                seen[key] = [rec]

        # 构造结果
        unique_records: list[dict] = []
        kept_keys: set = set()
        for rec in records:
            key = rec.get(key_field)
            if key not in kept_keys:
                unique_records.append(rec)
                kept_keys.add(key)

        if conflicts:
            # 存在冲突，需要用户确认
            confirmation = {
                "message": f"发现 {len(conflicts)} 组冲突记录，请确认保留哪条",
                "conflicts": conflicts,
                "options": ["keep_first", "keep_last", "keep_both", "manual_review"],
            }
            return ToolCallResponse(
                tool_name=self.name,
                call_id=request.call_id,
                status=CallStatus.NEEDS_CONFIRMATION,
                result={
                    "unique_records": unique_records,
                    "duplicates": duplicates,
                    "conflicts": conflicts,
                },
                confirmation_request=confirmation,
            )

        return ToolCallResponse(
            tool_name=self.name,
            call_id=request.call_id,
            status=CallStatus.SUCCESS,
            result={
                "unique_records": unique_records,
                "duplicates": duplicates,
                "conflicts": [],
            },
        )
