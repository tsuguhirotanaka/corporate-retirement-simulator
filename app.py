"""
法人経営者向け 老後資金シミュレーター
複数の法人保険（最大10件）＋退職金・相続・老後キャッシュフローの最適設計ツール
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import datetime

# ─────────────────────────────────────────
# 定数
# ─────────────────────────────────────────
LIFE_INSURANCE_EXEMPTION_PER_HEIR = 5_000_000  # 相続税非課税枠：500万円×法定相続人数

EXIT_OPTIONS = [
    "① 解約して退職金として受取",
    "② 現物支給（法人→本人へ名義変更）",
    "③ 後継者へ名義変更",
]

EXIT_NOTES = {
    "① 解約して退職金として受取":
        "法人が解約し、解約返戻金を役員退職金として支給。退職所得控除が適用されます。",
    "② 現物支給（法人→本人へ名義変更）":
        "保険契約ごと経営者個人に名義変更。個人で継続でき、将来の解約金・死亡保険金を活用可能。低解約返戻期間中の変更が節税のカギです。",
    "③ 後継者へ名義変更":
        "後継者に名義変更し、事業承継と後継者の退職金積立を兼ねます。",
}

INSURANCE_TYPES = ["終身保険", "逓増定期保険", "養老保険", "定期保険", "その他"]

# ─────────────────────────────────────────
# 計算関数
# ─────────────────────────────────────────
def calc_income_tax(income: int) -> float:
    brackets = [
        (1_950_000, 0.05, 0),
        (3_300_000, 0.10, 97_500),
        (6_950_000, 0.20, 427_500),
        (9_000_000, 0.23, 636_000),
        (18_000_000, 0.33, 1_536_000),
        (40_000_000, 0.40, 2_796_000),
        (float("inf"), 0.45, 4_796_000),
    ]
    for limit, rate, deduction in brackets:
        if income <= limit:
            return max(0, income * rate - deduction)
    return income * 0.45 - 4_796_000

def calc_retirement_deduction(years: int) -> int:
    if years <= 0:
        return 0
    elif years <= 20:
        return max(800_000, 400_000 * years)
    else:
        return 8_000_000 + 700_000 * (years - 20)

def calc_retirement_tax(retirement_income: int, years: int) -> dict:
    deduction = calc_retirement_deduction(years)
    taxable_base = max(0, retirement_income - deduction)
    taxable_income = taxable_base // 2
    income_tax = calc_income_tax(taxable_income) * 1.021
    resident_tax = taxable_income * 0.10
    total_tax = income_tax + resident_tax
    net = max(0, retirement_income - total_tax)
    return {
        "退職金総額": retirement_income,
        "退職所得控除額": deduction,
        "課税対象額（控除後÷2）": taxable_income,
        "所得税（復興税込）": int(income_tax),
        "住民税": int(resident_tax),
        "税金合計": int(total_tax),
        "実質手取り": int(net),
        "実効税率": total_tax / retirement_income * 100 if retirement_income > 0 else 0,
    }

def calc_nisa(monthly: int, years: int, annual_return: float) -> dict:
    """NISA（新NISA）の積立試算。運用益は非課税。"""
    total_paid = monthly * 12 * years
    mr = annual_return / 12 / 100
    if mr > 0:
        total_asset = int(monthly * ((1 + mr) ** (years * 12) - 1) / mr)
    else:
        total_asset = total_paid
    profit = total_asset - total_paid
    # 通常課税（20.315%）との比較で節税効果を算出
    tax_saving = int(profit * 0.20315)
    return {
        "掛金総額": total_paid,
        "積立総額（運用込・非課税）": total_asset,
        "運用益（非課税）": profit,
        "節税効果（通常課税比）": tax_saving,
    }

def calc_kyosai(monthly: int, years: int) -> dict:
    total_paid = monthly * 12 * years
    rate = 1.20 if years >= 20 else 1.15 if years >= 15 else 1.10 if years >= 10 else 1.05
    receive = int(total_paid * rate)
    tax_saving = int(monthly * 12 * 0.30 * years)
    return {"掛金総額": total_paid, "受取概算額": receive, "節税総額（概算）": tax_saving,
            "年間節税額（概算）": int(monthly * 12 * 0.30)}

def calc_ideco(monthly: int, years: int, annual_return: float) -> dict:
    total_paid = monthly * 12 * years
    mr = annual_return / 12 / 100
    total_asset = int(monthly * ((1 + mr) ** (years * 12) - 1) / mr) if mr > 0 else total_paid
    tax_saving = int(monthly * 12 * 0.30 * years)
    return {"掛金総額": total_paid, "積立総額（運用込）": total_asset,
            "運用益": total_asset - total_paid, "節税総額（概算）": tax_saving,
            "年間節税額（概算）": int(monthly * 12 * 0.30)}

def calc_insurance(monthly: int, years: int, return_rate: float, death_benefit: int) -> dict:
    total = monthly * 12 * years
    surrender = int(total * return_rate / 100)
    tax_saving_year = int(monthly * 12 * 0.5 * 0.30)
    return {
        "保険料総額": total,
        "解約返戻金（概算）": surrender,
        "死亡保険金": death_benefit,
        "年間節税額（概算）": tax_saving_year,
        "節税総額（概算）": tax_saving_year * years,
    }

def calc_yakuin(last_salary: int, years: int, multiplier: float) -> int:
    return int(last_salary * years * multiplier)

def calc_cashflow(retire_age, life_expectancy, net_retirement, monthly_pension, monthly_expense):
    records = []
    remaining = net_retirement
    pension_start = max(retire_age, 65)
    for age in range(retire_age, life_expectancy + 1):
        annual_pension = monthly_pension * 12 if age >= pension_start else 0
        annual_expense = monthly_expense * 12
        annual_balance = annual_pension - annual_expense
        remaining += annual_balance
        records.append({
            "年齢": age,
            "年金収入（年）": annual_pension,
            "生活費（年）": annual_expense,
            "年間収支": annual_balance,
            "資産残高": int(remaining),
        })
    return pd.DataFrame(records)

# ─────────────────────────────────────────
# ページ設定・スタイル
# ─────────────────────────────────────────
st.set_page_config(page_title="法人経営者向け 老後資金シミュレーター", page_icon="🏢", layout="wide")

st.markdown("""
<style>
.main-box {
    background: linear-gradient(135deg, #1a3a5c 0%, #0d6efd 100%);
    color: white; border-radius: 16px; padding: 24px 32px;
    margin-bottom: 20px; box-shadow: 0 4px 20px rgba(13,110,253,0.3);
}
.main-box h2 { color: #ffe066; margin: 0 0 8px 0; font-size: 1.4rem; }
.ins-card {
    background: #f8fbff; border: 1.5px solid #c5d8f5;
    border-radius: 12px; padding: 16px 20px; margin-bottom: 12px;
}
.ins-header {
    background: #1a3a5c; color: white; border-radius: 8px;
    padding: 6px 14px; font-weight: bold; font-size: 0.95rem;
    display: inline-block; margin-bottom: 12px;
}
.warn-box {
    background: #fff3cd; border-left: 4px solid #ffc107;
    border-radius: 8px; padding: 12px 16px; margin: 10px 0; font-size: 0.9rem;
}
.gap-box {
    background: #fff0f0; border-left: 4px solid #dc3545;
    border-radius: 8px; padding: 16px 20px; margin: 10px 0;
}
.ok-box {
    background: #f0fff4; border-left: 4px solid #28a745;
    border-radius: 8px; padding: 16px 20px; margin: 10px 0;
}
</style>
""", unsafe_allow_html=True)

st.title("🏢 法人経営者向け 老後資金シミュレーター")
st.caption("複数の法人保険（最大10件）＋退職金・相続・老後キャッシュフローの最適設計ツール")

# ─────────────────────────────────────────
# session_state：保険件数の管理
# ─────────────────────────────────────────
if "num_policies" not in st.session_state:
    st.session_state["num_policies"] = 1
if "num_personal_ins" not in st.session_state:
    st.session_state["num_personal_ins"] = 1

# ─────────────────────────────────────────
# 保存・読み込み機能
# ─────────────────────────────────────────
def collect_save_data() -> dict:
    """現在のsession_stateから保存対象のキーを収集してdictで返す"""
    keys = [
        "current_age", "retire_age", "life_expectancy", "num_heirs",
        "last_salary", "years_as_director", "multiplier",
        "monthly_pension", "monthly_expense",
        "kyosai_monthly", "kyosai_y",
        "ideco_monthly", "ideco_y", "ideco_return",
        "nisa_monthly", "nisa_y", "nisa_return", "nisa_type",
        "savings_current", "savings_annual", "sav_y",
        "ideal_monthly", "ideal_asset",
        "num_policies", "num_personal_ins",
    ]
    # 法人保険（動的キー）
    n_pol = st.session_state.get("num_policies", 1)
    for i in range(n_pol):
        for suffix in ["ins_name", "ins_type", "ins_m", "ins_y", "ins_r", "ins_d", "ins_exit"]:
            keys.append(f"{suffix}_{i}")
    # 個人保険（動的キー）
    n_pins = st.session_state.get("num_personal_ins", 1)
    for i in range(n_pins):
        for suffix in ["pins_name", "pins_type", "pins_recv", "pins_ann"]:
            keys.append(f"{suffix}_{i}")

    return {k: st.session_state[k] for k in keys if k in st.session_state}

def apply_load_data(data: dict):
    """読み込んだdictをsession_stateに反映する"""
    for k, v in data.items():
        st.session_state[k] = v

# ── 保存・読み込みUI（フォームの上に常時表示）──
with st.container():
    sv_col1, sv_col2, sv_col3 = st.columns([2, 2, 5])

    # 保存ボタン
    if st.session_state.get("simulated"):
        save_data = collect_save_data()
        save_json = json.dumps(save_data, ensure_ascii=False, indent=2)
        filename = f"老後資金設定_{datetime.date.today().strftime('%Y%m%d')}.json"
        sv_col1.download_button(
            label="💾 設定を保存",
            data=save_json,
            file_name=filename,
            mime="application/json",
            help="現在の入力内容をJSONファイルとして保存します。次回読み込むことで復元できます。",
        )

    # 読み込みボタン
    uploaded = sv_col2.file_uploader(
        "📂 設定を読み込む",
        type=["json"],
        label_visibility="collapsed",
        help="以前保存したJSONファイルをアップロードすると入力値が復元されます。",
        key="upload_json",
    )
    if uploaded is not None:
        try:
            loaded = json.load(uploaded)
            apply_load_data(loaded)
            st.session_state["simulated"] = True
            st.success("✅ 設定を読み込みました！")
            st.rerun()
        except Exception as e:
            st.error(f"読み込みに失敗しました: {e}")

# ─────────────────────────────────────────
# 入力フォーム
# ─────────────────────────────────────────
with st.expander("📝 情報を入力する", expanded=not st.session_state.get("simulated")):

    # ── 共通：基本情報 ──
    st.markdown("#### 👤 基本情報")
    c1, c2, c3, c4 = st.columns(4)
    current_age     = c1.number_input("現在の年齢", 30, 75, 50, 1, key="current_age")
    retire_age      = c2.number_input("引退予定年齢", int(current_age)+1, 80, 65, 1, key="retire_age")
    life_expectancy = c3.number_input("想定寿命", 65, 100, 85, 1, key="life_expectancy")
    num_heirs       = c4.number_input("法定相続人の数", 1, 10, 2, 1, key="num_heirs",
                                      help="相続税非課税枠（500万円×人数）の計算に使います。")

    st.divider()

    # ── タブで法人／個人を分ける ──
    tab_corp, tab_personal = st.tabs(["🏢 法人の情報", "👤 個人の情報"])

    # ════════════════════════════════
    # 🏢 法人タブ
    # ════════════════════════════════
    with tab_corp:
        st.markdown("#### 💼 役員報酬・在任年数")
        c1, c2 = st.columns(2)
        last_salary       = c1.number_input("最終報酬月額（円）", 0, 5_000_000, 1_000_000, 50_000,
                                             format="%d", key="last_salary",
                                             help="功績倍率方式の役員退職金計算に使います。")
        years_as_director = c2.number_input("役員在任年数（引退時点）", 1, 50,
                                             int(retire_age - current_age + 10), 1,
                                             key="years_as_director")

        st.divider()

        # 法人保険
        st.markdown("#### 🏦 法人保険（最大10件）")
        col_add, col_del, _ = st.columns([1, 1, 5])
        if col_add.button("➕ 保険を追加", disabled=st.session_state["num_policies"] >= 10):
            st.session_state["num_policies"] += 1
            st.rerun()
        if col_del.button("➖ 保険を削除", disabled=st.session_state["num_policies"] <= 1):
            st.session_state["num_policies"] -= 1
            st.rerun()

        policies = []
        for i in range(st.session_state["num_policies"]):
            st.markdown(f'<div class="ins-header">保険 {i+1}</div>', unsafe_allow_html=True)
            with st.container():
                c1, c2 = st.columns([2, 5])
                ins_name = c1.text_input("保険名", value=f"終身保険{i+1}", key=f"ins_name_{i}")
                ins_type = c2.selectbox("種類", INSURANCE_TYPES, key=f"ins_type_{i}")

                c1, c2, c3, c4 = st.columns(4)
                ins_monthly = c1.number_input("月額保険料（円）", 0, 5_000_000, 200_000, 10_000,
                                              format="%d", key=f"ins_m_{i}")
                ins_years   = c2.number_input("払込年数", 1, 40, int(retire_age - current_age), 1,
                                              key=f"ins_y_{i}")
                ins_rate    = c3.number_input("解約返戻率（%）", 0.0, 120.0, 90.0, 1.0,
                                              key=f"ins_r_{i}",
                                              help="引退時点での解約返戻率（保険設計書で確認）")
                ins_death   = c4.number_input("死亡保険金（万円）", 0, 100_000, 10_000, 500,
                                              format="%d", key=f"ins_d_{i}") * 10_000

                ins_exit = st.radio("出口戦略", EXIT_OPTIONS, key=f"ins_exit_{i}",
                                    horizontal=True,
                                    help="① 解約して退職金に / ② 個人に名義変更して継続 / ③ 後継者に承継")
                st.caption(f"💡 {EXIT_NOTES[ins_exit]}")

                result = calc_insurance(ins_monthly, ins_years, ins_rate, ins_death)
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("保険料総額", f"{result['保険料総額']/10000:,.0f}万円")
                mc2.metric("解約返戻金（概算）", f"{result['解約返戻金（概算）']/10000:,.0f}万円")
                mc3.metric("死亡保険金", f"{ins_death/10000:,.0f}万円")

                policies.append({
                    "名称": ins_name, "種類": ins_type, "月額": ins_monthly,
                    "払込年数": ins_years, "返戻率": ins_rate,
                    "解約返戻金": result["解約返戻金（概算）"],
                    "死亡保険金": ins_death,
                    "保険料総額": result["保険料総額"],
                    "節税総額": result["節税総額（概算）"],
                    "年間節税額": result["年間節税額（概算）"],
                    "出口戦略": ins_exit,
                })
            if i < st.session_state["num_policies"] - 1:
                st.markdown("<hr style='border:1px dashed #c5d8f5; margin:8px 0;'>", unsafe_allow_html=True)

        st.divider()

        # 小規模企業共済
        st.markdown("#### 🏛️ 小規模企業共済")
        c1, c2 = st.columns(2)
        kyosai_monthly = c1.number_input("掛金月額（円）※最大70,000円", 0, 70_000, 70_000, 1_000,
                                          format="%d", key="kyosai_monthly")
        kyosai_years   = c2.number_input("加入年数（引退時点）", 0, 45, int(retire_age - current_age), 1,
                                          key="kyosai_y")

        st.divider()

        # 役員退職金
        st.markdown("#### 🏆 役員退職金の設計（功績倍率方式）")
        c1, c2 = st.columns(2)
        multiplier    = c1.number_input("功績倍率", 0.5, 3.0, 2.0, 0.1, key="multiplier",
                                         help="代表取締役：2.0〜3.0倍、取締役：1.5〜2.0倍が目安")
        yakuin_amount = calc_yakuin(last_salary, years_as_director, multiplier)
        c2.markdown(f"""
<div style="background:#eef4ff;border-radius:8px;padding:12px 16px;margin-top:8px;">
役員退職金の適正額（目安）<br>
<strong style="font-size:1.3rem;">{yakuin_amount/10000:,.0f}万円</strong><br>
<small>= 月額{last_salary:,}円 × {years_as_director}年 × {multiplier}倍</small>
</div>
""", unsafe_allow_html=True)

    # ════════════════════════════════
    # 👤 個人タブ
    # ════════════════════════════════
    with tab_personal:

        # 公的年金・生活費
        st.markdown("#### 💴 公的年金・生活費")
        c1, c2 = st.columns(2)
        monthly_pension = c1.number_input("公的年金 月額（円）", 0, 500_000, 150_000, 5_000,
                                           format="%d", key="monthly_pension")
        monthly_expense = c2.number_input("引退後の月々の生活費（円）", 0, 2_000_000, 300_000, 10_000,
                                           format="%d", key="monthly_expense")

        st.divider()

        # iDeCo
        st.markdown("#### 📈 iDeCo（個人型確定拠出年金）")
        c1, c2, c3 = st.columns(3)
        ideco_monthly = c1.number_input("掛金月額（円）※経営者最大23,000円", 0, 23_000, 23_000, 1_000,
                                         format="%d", key="ideco_monthly")
        ideco_years   = c2.number_input("加入年数（引退時点）", 0, 40, int(retire_age - current_age), 1,
                                         key="ideco_y")
        ideco_return  = c3.number_input("想定運用利率（%）", 0.0, 10.0, 3.0, 0.5, key="ideco_return")

        st.divider()

        # NISA
        st.markdown("#### 📊 NISA（新NISA）")
        st.caption("年間360万円まで非課税で投資可能。運用益・売却益が永久非課税。")
        c1, c2, c3, c4 = st.columns(4)
        nisa_monthly = c1.number_input("月額積立（円）", 0, 300_000, 100_000, 10_000, format="%d",
                                        key="nisa_monthly", help="最大30万円/月（年360万円）")
        nisa_years   = c2.number_input("積立年数", 0, 40, int(retire_age - current_age), 1, key="nisa_y")
        nisa_return  = c3.number_input("想定運用利率（%）", 0.0, 15.0, 5.0, 0.5, key="nisa_return",
                                        help="長期インデックス投資の目安：年3〜7%")
        nisa_type    = c4.selectbox("主な投資枠", ["つみたて投資枠", "成長投資枠", "両方（併用）"],
                                     key="nisa_type")

        st.divider()

        # 預貯金
        st.markdown("#### 🏧 預貯金・現金資産")
        st.caption("現在の預貯金残高と、引退までの年間積立額を入力してください。")
        c1, c2, c3 = st.columns(3)
        savings_current = c1.number_input(
            "現在の預貯金残高（万円）", 0, 100_000, 1_000, 100, format="%d",
            help="老後に使える預貯金の合計。"
        ) * 10_000
        savings_annual  = c2.number_input(
            "引退まで毎年の積立額（万円）", 0, 10_000, 100, 50, format="%d",
        ) * 10_000
        savings_years   = c3.number_input(
            "積立年数", 0, 40, int(retire_age - current_age), 1, key="sav_y"
        )

        st.divider()

        # 個人保険
        st.markdown("#### 🧑 個人で契約している保険")
        st.caption("個人名義の生命保険・個人年金保険などの解約返戻金・満期金を入力してください。")

        if "num_personal_ins" not in st.session_state:
            st.session_state["num_personal_ins"] = 1

        pc1, pc2, _ = st.columns([1, 1, 5])
        if pc1.button("➕ 追加", key="add_pins", disabled=st.session_state["num_personal_ins"] >= 5):
            st.session_state["num_personal_ins"] += 1
            st.rerun()
        if pc2.button("➖ 削除", key="del_pins", disabled=st.session_state["num_personal_ins"] <= 1):
            st.session_state["num_personal_ins"] -= 1
            st.rerun()

        personal_policies = []
        personal_ins_types = ["終身保険（個人）", "個人年金保険", "養老保険", "学資保険", "その他"]
        for i in range(st.session_state["num_personal_ins"]):
            st.markdown(f'<div class="ins-header">個人保険 {i+1}</div>', unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            pins_name    = c1.text_input("保険名", value=f"個人保険{i+1}", key=f"pins_name_{i}")
            pins_type    = c2.selectbox("種類", personal_ins_types, key=f"pins_type_{i}")
            pins_receive = c3.number_input(
                "引退時の受取見込額（万円）", 0, 100_000, 500, 100,
                format="%d", key=f"pins_recv_{i}",
                help="解約返戻金・満期金・個人年金の一時金受取額の見込み。"
            ) * 10_000
            pins_monthly_annuity = c4.number_input(
                "年金月額（円）※年金型の場合", 0, 500_000, 0, 10_000,
                format="%d", key=f"pins_ann_{i}",
                help="個人年金保険など月々受け取る場合の月額。一時金の場合は0。"
            )
            personal_policies.append({
                "名称": pins_name,
                "種類": pins_type,
                "受取見込額": pins_receive,
                "年金月額": pins_monthly_annuity,
            })
            if i < st.session_state["num_personal_ins"] - 1:
                st.markdown("<hr style='border:1px dashed #c5d8f5; margin:8px 0;'>", unsafe_allow_html=True)

    # タブの外：理想設定＋実行ボタン
    st.divider()
    st.markdown("#### 🎯 理想の老後設定")
    c1, c2 = st.columns(2)
    ideal_monthly = c1.number_input("引退後に欲しい月収（円）", 0, 2_000_000, 500_000, 10_000,
                                     format="%d", key="ideal_monthly")
    ideal_asset   = c2.number_input("死亡時に残したい資産（万円）", 0, 100_000, 3_000, 500,
                                     format="%d", key="ideal_asset") * 10_000

    st.divider()
    run_btn = st.button("🔍 シミュレーション実行", type="primary", use_container_width=True)
    if run_btn:
        st.session_state["simulated"] = True

if not st.session_state.get("simulated"):
    st.info("👆 上のフォームに情報を入力し、「シミュレーション実行」を押してください。")
    with st.expander("📖 主な用語の説明"):
        st.markdown("""
| 用語 | 説明 |
|------|------|
| **解約返戻率** | 払い込んだ保険料に対し解約時に戻ってくる割合。保険設計書で確認。 |
| **現物支給（名義変更）** | 法人→個人へ保険契約ごと譲渡。低解約返戻期間中が節税のカギ。 |
| **小規模企業共済** | 経営者の退職金制度。掛金全額が所得控除。月最大7万円。 |
| **功績倍率方式** | 役員退職金 = 最終報酬月額 × 勤続年数 × 功績倍率 |
| **退職所得控除** | 勤続年数に応じて退職金から差し引かれる控除額。長期在任ほど有利。 |
| **iDeCo** | 個人型確定拠出年金。法人経営者は月最大2.3万円。掛金全額所得控除。 |
        """)
    st.stop()

# ─────────────────────────────────────────
# 計算実行
# ─────────────────────────────────────────
kyosai = calc_kyosai(kyosai_monthly, kyosai_years)
ideco  = calc_ideco(ideco_monthly, ideco_years, ideco_return)
nisa   = calc_nisa(nisa_monthly, nisa_years, nisa_return)

# 預貯金：現在残高＋積立
total_savings = int(savings_current + savings_annual * savings_years)

# 個人保険：一時金の合計
total_personal_ins = sum(p["受取見込額"] for p in personal_policies)
# 個人保険：年金月額の合計
total_personal_annuity = sum(p["年金月額"] for p in personal_policies)

# 保険の集計
total_surrender   = sum(p["解約返戻金"] for p in policies if p["出口戦略"] == EXIT_OPTIONS[0])
total_death       = sum(p["死亡保険金"] for p in policies)
total_ins_premium = sum(p["保険料総額"] for p in policies)
total_ins_tax     = sum(p["節税総額"] for p in policies)

# 退職金総額（法人保険解約＋共済＋iDeCo＋NISA＋預貯金＋個人保険）
retirement_total = (total_surrender + kyosai["受取概算額"] + ideco["積立総額（運用込）"]
                    + nisa["積立総額（運用込・非課税）"] + total_savings + total_personal_ins)

# 退職所得控除・税金
ret_tax = calc_retirement_tax(retirement_total, years_as_director)

# 相続税非課税枠
inheritance_exemption = LIFE_INSURANCE_EXEMPTION_PER_HEIR * num_heirs

# 老後キャッシュフロー
cf_df = calc_cashflow(
    retire_age, life_expectancy,
    ret_tax["実質手取り"],
    monthly_pension + total_personal_annuity,  # 公的年金＋個人年金
    monthly_expense
)
depleted = cf_df[cf_df["資産残高"] <= 0]["年齢"].tolist()
depleted_age = depleted[0] if depleted else None

# ギャップ分析
pension_start = max(retire_age, 65)
pension_total = monthly_pension * 12 * (life_expectancy - pension_start)
required_total = ideal_monthly * 12 * (life_expectancy - retire_age)
gap = required_total - pension_total - ret_tax["実質手取り"]

# ─────────────────────────────────────────
# [1] 総合サマリー
# ─────────────────────────────────────────
st.markdown("## 💡 シミュレーション結果")

# ── 総合サマリー（最上部）──
st.markdown(f"""
<div class="main-box">
  <h2>🏆 引退時の総資産（手取りベース）</h2>
  <div style="font-size:2.2rem; font-weight:900; color:#ffe066;">
    約{ret_tax["実質手取り"]/10000:,.0f}万円
  </div>
  <div style="font-size:0.95rem; line-height:1.9; margin-top:8px;">
    資産総額：{retirement_total/10000:,.0f}万円　→　退職所得控除▼{ret_tax["退職所得控除額"]/10000:,.0f}万円　→　税金▼{ret_tax["税金合計"]/10000:,.0f}万円（実効税率{ret_tax["実効税率"]:.1f}%）
  </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════
# 法人サイド ／ 個人サイド の2列表示
# ══════════════════════════════════════════
col_corp, col_divider, col_personal = st.columns([10, 1, 10])

# ── 法人サイド ──
with col_corp:
    st.markdown("""
<div style="background:#1a3a5c;color:white;border-radius:10px;
padding:10px 18px;font-size:1.1rem;font-weight:bold;margin-bottom:16px;">
🏢 法人の持ち物
</div>
""", unsafe_allow_html=True)

    # 法人保険
    st.markdown("**🏦 法人保険（解約返戻金）**")
    for p in policies:
        color = "#dbeafe" if "①" in p["出口戦略"] else "#dcfce7" if "②" in p["出口戦略"] else "#fef9c3"
        st.markdown(f"""
<div style="background:{color};border-radius:8px;padding:10px 14px;margin:6px 0;">
  <strong>{p['名称']}</strong>（{p['種類']}）<br>
  解約返戻金：<strong>{p['解約返戻金']/10000:,.0f}万円</strong>
  死亡保険金：<strong>{p['死亡保険金']/10000:,.0f}万円</strong><br>
  <span style="font-size:0.85rem;color:#555;">{p['出口戦略']}</span>
</div>
""", unsafe_allow_html=True)

    st.markdown(f"""
<div style="background:#f0f4ff;border-radius:8px;padding:10px 14px;margin:8px 0;">
  法人保険 合計　解約返戻金：<strong>{total_surrender/10000:,.0f}万円</strong>
  死亡保険金：<strong>{total_death/10000:,.0f}万円</strong>
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # 役員退職金
    st.markdown("**🏆 役員退職金（適正額目安）**")
    st.markdown(f"""
<div style="background:#fff9e6;border-radius:8px;padding:10px 14px;margin:6px 0;">
  最終報酬月額 {last_salary/10000:.0f}万円 × {years_as_director}年 × 功績倍率{multiplier}倍<br>
  → <strong>{yakuin_amount/10000:,.0f}万円</strong>
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # 小規模企業共済（法人経営者向けだが個人名義。ここでは法人側に表示）
    st.markdown("**🏛️ 小規模企業共済**")
    st.markdown(f"""
<div style="background:#f0f4ff;border-radius:8px;padding:10px 14px;margin:6px 0;">
  掛金月額 {kyosai_monthly/10000:.1f}万円 × {kyosai_years}年<br>
  受取見込：<strong>{kyosai["受取概算額"]/10000:,.0f}万円</strong>
  節税総額：{kyosai["節税総額（概算）"]/10000:.0f}万円
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")
    corp_total = total_surrender + kyosai["受取概算額"]
    st.markdown(f"""
<div style="background:#1a3a5c;color:white;border-radius:8px;padding:12px 16px;margin-top:8px;">
  🏢 法人サイド 合計（引退時受取）：<strong style="font-size:1.2rem;color:#ffe066;">
  {corp_total/10000:,.0f}万円</strong>
</div>
""", unsafe_allow_html=True)

# ── 区切り ──
with col_divider:
    st.markdown("""
<div style="height:100%;border-left:2px dashed #dee2e6;margin:0 auto;width:0;min-height:600px;"></div>
""", unsafe_allow_html=True)

# ── 個人サイド ──
with col_personal:
    st.markdown("""
<div style="background:#0d6efd;color:white;border-radius:10px;
padding:10px 18px;font-size:1.1rem;font-weight:bold;margin-bottom:16px;">
👤 個人の持ち物
</div>
""", unsafe_allow_html=True)

    # iDeCo
    st.markdown("**📈 iDeCo**")
    st.markdown(f"""
<div style="background:#f0fdf4;border-radius:8px;padding:10px 14px;margin:6px 0;">
  月額 {ideco_monthly/10000:.1f}万円 × {ideco_years}年（利率{ideco_return}%）<br>
  積立総額：<strong>{ideco["積立総額（運用込）"]/10000:,.0f}万円</strong>（運用益：{ideco["運用益"]/10000:.0f}万円）<br>
  節税総額：{ideco["節税総額（概算）"]/10000:.0f}万円
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # NISA
    st.markdown("**📊 NISA（新NISA）**")
    st.markdown(f"""
<div style="background:#f0fdf4;border-radius:8px;padding:10px 14px;margin:6px 0;">
  月額 {nisa_monthly/10000:.1f}万円 × {nisa_years}年（利率{nisa_return}%・{nisa_type}）<br>
  積立総額：<strong>{nisa["積立総額（運用込・非課税）"]/10000:,.0f}万円</strong>（非課税運用益：{nisa["運用益（非課税）"]/10000:.0f}万円）<br>
  節税効果（課税口座比）：{nisa["節税効果（通常課税比）"]/10000:.0f}万円
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # 預貯金
    st.markdown("**🏧 預貯金・現金資産**")
    st.markdown(f"""
<div style="background:#fffbeb;border-radius:8px;padding:10px 14px;margin:6px 0;">
  現在残高：{savings_current/10000:,.0f}万円　＋　積立予定：{savings_annual/10000:.0f}万円×{savings_years}年<br>
  引退時合計：<strong>{total_savings/10000:,.0f}万円</strong>
</div>
""", unsafe_allow_html=True)

    st.markdown("&nbsp;")

    # 個人保険
    st.markdown("**🧑 個人保険**")
    if personal_policies:
        for p in personal_policies:
            st.markdown(f"""
<div style="background:#fffbeb;border-radius:8px;padding:10px 14px;margin:6px 0;">
  <strong>{p['名称']}</strong>（{p['種類']}）<br>
  受取見込：<strong>{p['受取見込額']/10000:,.0f}万円</strong>
  {"　年金月額：" + f"{p['年金月額']:,}円" if p['年金月額'] > 0 else ""}
</div>
""", unsafe_allow_html=True)
    else:
        st.caption("なし")

    st.markdown("&nbsp;")
    personal_total = ideco["積立総額（運用込）"] + nisa["積立総額（運用込・非課税）"] + total_savings + total_personal_ins
    st.markdown(f"""
<div style="background:#0d6efd;color:white;border-radius:8px;padding:12px 16px;margin-top:8px;">
  👤 個人サイド 合計（引退時受取）：<strong style="font-size:1.2rem;color:#ffe066;">
  {personal_total/10000:,.0f}万円</strong>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── 相続対策 ──
st.markdown("## 🛡️ 万が一の場合・相続対策")
c1, c2, c3 = st.columns(3)
c1.metric("死亡保険金合計（法人保険）", f"{total_death/10000:,.0f}万円")
c2.metric("相続税非課税枠", f"{inheritance_exemption/10000:,.0f}万円",
          help=f"500万円 × {num_heirs}人")
c3.metric("非課税対象額", f"{min(total_death, inheritance_exemption)/10000:,.0f}万円")

if total_personal_annuity > 0:
    st.info(f"💡 個人年金の月額合計：{total_personal_annuity:,}円 → 老後の毎月の収入に加算されています。")

st.divider()

# ─────────────────────────────────────────
# [3] ギャップ分析・対策提案
# ─────────────────────────────────────────
st.markdown("## 📊 現状診断・ギャップ分析")

c1, c2, c3 = st.columns(3)
c1.metric("必要老後資金（総額）", f"{required_total/10000:,.0f}万円")
c2.metric("準備できている資金", f"{(ret_tax['実質手取り']+pension_total)/10000:,.0f}万円")
c3.metric("過不足", f"{'▼' if gap>0 else '▲'}{abs(gap)/10000:,.0f}万円",
          delta_color="inverse" if gap > 0 else "normal")

if depleted_age:
    st.markdown(f"""<div class="gap-box">
⚠️ <strong>資産が尽きる年齢：{depleted_age}歳</strong>
想定寿命{life_expectancy}歳まであと<strong>{life_expectancy - depleted_age}年分</strong>の資金が不足しています。
</div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""<div class="ok-box">
✅ <strong>想定寿命{life_expectancy}歳まで資産が持続します。</strong>
{life_expectancy}歳時点の残資産：約{cf_df.iloc[-1]["資産残高"]/10000:,.0f}万円
</div>""", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────
# [4] 対策提案
# ─────────────────────────────────────────
st.markdown("## 💡 対策提案")

proposals = []
if kyosai_monthly < 70_000:
    diff = 70_000 - kyosai_monthly
    proposals.append({"優先度": "🔴 高",
        "提案": f"小規模企業共済を月{diff:,}円増額して満額（7万円）にする",
        "効果": f"年間節税額が約{int(diff*12*0.30/10000)}万円増加"})

if all(p["出口戦略"] == EXIT_OPTIONS[0] for p in policies) and len(policies) >= 1:
    proposals.append({"優先度": "🟡 中",
        "提案": "一部の保険を現物支給（②）にして個人での継続を検討する",
        "効果": "相続対策として死亡保険金を個人で活用でき、資産の柔軟性が高まる"})

if ideco_monthly < 23_000:
    diff = 23_000 - ideco_monthly
    proposals.append({"優先度": "🟡 中",
        "提案": f"iDeCoを月{diff:,}円増額して上限（2.3万円）まで活用する",
        "効果": f"年間節税額が約{int(diff*12*0.30/10000)}万円増加"})

if depleted_age and depleted_age < life_expectancy:
    proposals.append({"優先度": "🔴 高",
        "提案": f"引退を{min(3, life_expectancy-depleted_age)}年延ばして{retire_age+min(3, life_expectancy-depleted_age)}歳にする",
        "効果": "在任年数が増え退職所得控除が拡大。積立期間も延長できる"})

if total_death < 50_000_000:
    proposals.append({"優先度": "🟢 情報",
        "提案": "死亡保険金の増額を検討する",
        "効果": f"相続税非課税枠（{inheritance_exemption/10000:,.0f}万円）をフル活用できていない可能性があります"})

if proposals:
    st.dataframe(pd.DataFrame(proposals), use_container_width=True, hide_index=True)
else:
    st.success("現在の設定で理想の老後資金が準備できています！")

st.divider()

# ─────────────────────────────────────────
# [5] 退職所得控除・税金明細
# ─────────────────────────────────────────
st.divider()

# ─────────────────────────────────────────
# NISA詳細
# ─────────────────────────────────────────
st.markdown("## 📊 NISA（新NISA）詳細")

c1, c2, c3, c4 = st.columns(4)
c1.metric("月額積立", f"{nisa_monthly/10000:.1f}万円")
c2.metric("積立総額（元本）", f"{nisa['掛金総額']/10000:,.0f}万円")
c3.metric("積立総額（運用込・非課税）", f"{nisa['積立総額（運用込・非課税）']/10000:,.0f}万円")
c4.metric("運用益（非課税）", f"{nisa['運用益（非課税）']/10000:,.0f}万円")

st.markdown(f"""
<div class="ok-box">
💡 <strong>NISAの非課税メリット</strong><br>
通常の課税口座で同額を運用した場合、運用益{nisa['運用益（非課税）']/10000:,.0f}万円に対して
約<strong>{nisa['節税効果（通常課税比）']/10000:,.0f}万円</strong>の税金（20.315%）がかかります。
NISAではこれが<strong>永久非課税</strong>となります。<br>
投資枠：{nisa_type}　／　想定利率：{nisa_return}%　／　積立年数：{nisa_years}年
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="warn-box">
⚠️ <strong>注意</strong>：NISAは元本保証ではありません。投資リスクを十分ご理解の上、ご活用ください。
新NISAの年間投資上限は1,800万円（生涯非課税枠）です。
</div>
""", unsafe_allow_html=True)

st.divider()

st.markdown("## 🏆 役員退職金・退職所得控除の明細")

c1, c2 = st.columns(2)
with c1:
    st.metric("役員退職金の適正額（目安）",
              f"{yakuin_amount/10000:,.0f}万円",
              help=f"月額{last_salary:,}円 × {years_as_director}年 × {multiplier}倍")

tax_data = pd.DataFrame({
    "項目": ["退職金総額", "退職所得控除額", "課税対象（控除後÷2）",
             "所得税（復興税込）", "住民税", "税金合計", "✅ 実質手取り"],
    "金額": [
        f"{ret_tax['退職金総額']/10000:,.0f}万円",
        f"▼{ret_tax['退職所得控除額']/10000:,.0f}万円",
        f"{ret_tax['課税対象額（控除後÷2）']/10000:,.0f}万円",
        f"▼{ret_tax['所得税（復興税込）']/10000:,.1f}万円",
        f"▼{ret_tax['住民税']/10000:,.1f}万円",
        f"▼{ret_tax['税金合計']/10000:,.0f}万円",
        f"{ret_tax['実質手取り']/10000:,.0f}万円",
    ]
})
st.dataframe(tax_data, use_container_width=True, hide_index=True)

with st.expander("📐 退職所得控除の計算式"):
    st.markdown(f"""
**勤続年数：{years_as_director}年の場合**

{'20年以下：40万円 × ' + str(years_as_director) + '年' if years_as_director <= 20 else '20年超：800万円 ＋ 70万円 × (' + str(years_as_director) + ' − 20)年'}

= **{ret_tax['退職所得控除額']/10000:,.0f}万円**

| 勤続年数 | 控除額の計算式 |
|---------|-------------|
| 20年以下 | 40万円 × 勤続年数（最低80万円） |
| 20年超  | 800万円 ＋ 70万円 × （勤続年数 − 20年） |
    """)

st.divider()

# ─────────────────────────────────────────
# [6] 老後キャッシュフロー
# ─────────────────────────────────────────
st.markdown("## 📈 老後キャッシュフロー")

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=cf_df["年齢"], y=cf_df["資産残高"] / 10000,
    name="資産残高", fill="tozeroy",
    line=dict(color="#0d6efd", width=3),
    fillcolor="rgba(13,110,253,0.15)",
))
fig.add_hline(y=0, line_color="red", line_dash="dash", line_width=1.5)
if depleted_age:
    fig.add_vline(x=depleted_age, line_color="red", line_dash="dot",
                  annotation_text=f"資産ゼロ:{depleted_age}歳", annotation_position="top right")
if ideal_asset > 0:
    fig.add_hline(y=ideal_asset / 10000, line_color="green", line_dash="dash",
                  annotation_text=f"残したい資産:{ideal_asset/10000:,.0f}万円",
                  annotation_position="right")
fig.update_layout(
    title="引退後の資産残高の推移",
    xaxis_title="年齢", yaxis_title="資産残高（万円）",
    plot_bgcolor="white", paper_bgcolor="white", font=dict(size=13), height=400,
)
fig.update_yaxes(gridcolor="#e9ecef")
fig.update_xaxes(gridcolor="#e9ecef")
st.plotly_chart(fig, use_container_width=True)
st.dataframe(cf_df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────
# フッター
# ─────────────────────────────────────────
st.markdown("""
---
<div style="font-size:0.8rem; color:#6c757d; text-align:center;">
⚠️ <strong>免責事項</strong>：本シミュレーターは概算値の提供を目的としており、実際の税額・受取額は個人の状況により異なります。
保険・税務・法律に関する最終判断は、税理士・社会保険労務士・ファイナンシャルプランナー・保険担当者にご相談ください。
</div>
""", unsafe_allow_html=True)
