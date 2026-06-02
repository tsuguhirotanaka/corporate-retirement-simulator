"""
法人経営者向け 老後資金シミュレーター
終身保険を軸にした退職金・相続・老後キャッシュフローの最適設計ツール
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import datetime

# ─────────────────────────────────────────
# 定数
# ─────────────────────────────────────────
LIFE_INSURANCE_INHERITANCE_EXEMPTION = 5_000_000  # 相続税非課税枠：500万円×法定相続人数（1人分）

# ─────────────────────────────────────────
# 退職所得控除の計算
# ─────────────────────────────────────────
def calc_retirement_deduction(years: int) -> int:
    """勤続年数から退職所得控除額を計算"""
    if years <= 0:
        return 0
    elif years <= 20:
        return max(800_000, 400_000 * years)
    else:
        return 8_000_000 + 700_000 * (years - 20)

def calc_retirement_tax(retirement_income: int, years: int) -> dict:
    """
    退職金の税金・手取りを計算
    退職所得 =（退職金 − 退職所得控除）÷ 2
    """
    deduction = calc_retirement_deduction(years)
    taxable_base = max(0, retirement_income - deduction)
    taxable_income = taxable_base // 2  # 1/2課税

    # 所得税（累進課税）
    income_tax = calc_income_tax(taxable_income)
    income_tax_with_復興 = income_tax * 1.021  # 復興特別所得税

    # 住民税
    resident_tax = taxable_income * 0.10

    total_tax = income_tax_with_復興 + resident_tax
    net = retirement_income - total_tax

    return {
        "退職金総額": retirement_income,
        "退職所得控除額": deduction,
        "課税対象額（控除後÷2）": taxable_income,
        "所得税（復興税込）": int(income_tax_with_復興),
        "住民税": int(resident_tax),
        "税金合計": int(total_tax),
        "実質手取り": int(net),
        "実効税率": total_tax / retirement_income * 100 if retirement_income > 0 else 0,
    }

def calc_income_tax(income: int) -> float:
    """所得税の累進計算"""
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
            return income * rate - deduction
    return income * 0.45 - 4_796_000

# ─────────────────────────────────────────
# 小規模企業共済の計算
# ─────────────────────────────────────────
def calc_kyosai(monthly: int, years: int) -> dict:
    """小規模企業共済の受取額・節税額試算"""
    total_paid = monthly * 12 * years
    # 受取係数（簡易：掛金×年数×係数）
    # 実際は共済金額表に基づくが、ここでは概算
    # 20年以上：掛金合計の約120%、15年以上：115%、それ以下：110%
    if years >= 20:
        rate = 1.20
    elif years >= 15:
        rate = 1.15
    elif years >= 10:
        rate = 1.10
    else:
        rate = 1.05
    receive = int(total_paid * rate)

    # 節税額（掛金全額所得控除。実効税率30%で概算）
    annual_deduction = monthly * 12
    tax_saving_per_year = int(annual_deduction * 0.30)
    total_tax_saving = tax_saving_per_year * years

    return {
        "掛金月額": monthly,
        "加入年数": years,
        "掛金総額": total_paid,
        "受取概算額": receive,
        "年間節税額（概算）": tax_saving_per_year,
        "節税総額（概算）": total_tax_saving,
    }

# ─────────────────────────────────────────
# iDeCoの計算
# ─────────────────────────────────────────
def calc_ideco(monthly: int, years: int, annual_return: float) -> dict:
    """iDeCoの積立・節税試算"""
    total_paid = monthly * 12 * years
    # 複利運用
    monthly_return = annual_return / 12 / 100
    if monthly_return > 0:
        total_asset = monthly * ((1 + monthly_return) ** (years * 12) - 1) / monthly_return
    else:
        total_asset = total_paid

    annual_deduction = monthly * 12
    tax_saving_per_year = int(annual_deduction * 0.30)
    total_tax_saving = tax_saving_per_year * years

    return {
        "掛金月額": monthly,
        "加入年数": years,
        "掛金総額": int(total_paid),
        "積立総額（運用込）": int(total_asset),
        "運用益": int(total_asset - total_paid),
        "年間節税額（概算）": tax_saving_per_year,
        "節税総額（概算）": total_tax_saving,
    }

# ─────────────────────────────────────────
# 終身保険の計算
# ─────────────────────────────────────────
def calc_seimei(monthly_premium: int, years: int, return_rate: float,
                death_benefit: int) -> dict:
    """終身保険（法人契約）の試算"""
    total_premium = monthly_premium * 12 * years
    # 解約返戻金
    surrender_value = int(total_premium * return_rate / 100)
    # 損金算入（終身保険は原則1/2損金）
    損金率 = 0.5
    annual_損金 = monthly_premium * 12 * 損金率
    tax_saving_per_year = int(annual_損金 * 0.30)
    total_tax_saving = tax_saving_per_year * years

    return {
        "月額保険料": monthly_premium,
        "払込年数": years,
        "保険料総額": total_premium,
        "解約返戻金（概算）": surrender_value,
        "死亡保険金額": death_benefit,
        "年間節税額（損金1/2・概算）": tax_saving_per_year,
        "節税総額（概算）": total_tax_saving,
    }

# ─────────────────────────────────────────
# 役員退職金の適正額（功績倍率方式）
# ─────────────────────────────────────────
def calc_yakuin_taishokukin(last_salary: int, years: int, multiplier: float) -> int:
    """役員退職金 = 最終報酬月額 × 勤続年数 × 功績倍率"""
    return int(last_salary * years * multiplier)

# ─────────────────────────────────────────
# 老後キャッシュフロー
# ─────────────────────────────────────────
def calc_cashflow(
    retire_age: int,
    life_expectancy: int,
    net_retirement: int,      # 退職金手取り
    monthly_pension: int,     # 月々の公的年金
    monthly_expense: int,     # 月々の生活費
) -> pd.DataFrame:
    records = []
    remaining = net_retirement
    for age in range(retire_age, life_expectancy + 1):
        annual_pension = monthly_pension * 12
        annual_expense = monthly_expense * 12
        annual_balance = annual_pension - annual_expense
        remaining += annual_balance
        records.append({
            "年齢": age,
            "年金収入（年）": annual_pension,
            "生活費（年）": annual_expense,
            "年間収支": annual_balance,
            "資産残高": remaining,
        })
    return pd.DataFrame(records)

# ─────────────────────────────────────────
# ページ設定・スタイル
# ─────────────────────────────────────────
st.set_page_config(
    page_title="法人経営者向け 老後資金シミュレーター",
    page_icon="🏢",
    layout="wide",
)

st.markdown("""
<style>
.main-box {
    background: linear-gradient(135deg, #1a3a5c 0%, #0d6efd 100%);
    color: white;
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(13,110,253,0.3);
}
.main-box h2 { color: #ffe066; margin: 0 0 8px 0; font-size: 1.4rem; }
.section-card {
    background: #f8f9fa;
    border-left: 4px solid #0d6efd;
    border-radius: 8px;
    padding: 16px 20px;
    margin: 8px 0;
}
.warn-box {
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 10px 0;
    font-size: 0.9rem;
}
.gap-box {
    background: #fff0f0;
    border-left: 4px solid #dc3545;
    border-radius: 8px;
    padding: 16px 20px;
    margin: 10px 0;
}
.ok-box {
    background: #f0fff4;
    border-left: 4px solid #28a745;
    border-radius: 8px;
    padding: 16px 20px;
    margin: 10px 0;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# タイトル
# ─────────────────────────────────────────
st.title("🏢 法人経営者向け 老後資金シミュレーター")
st.caption("終身保険を軸にした退職金・相続・老後キャッシュフローの最適設計ツール")

# ─────────────────────────────────────────
# 入力フォーム
# ─────────────────────────────────────────
with st.expander("📝 基本情報を入力する", expanded=not st.session_state.get("simulated")):

    st.markdown("#### 👤 基本情報")
    col1, col2, col3 = st.columns(3)
    with col1:
        current_age = st.number_input("現在の年齢", min_value=30, max_value=75, value=50, step=1)
    with col2:
        retire_age = st.number_input("引退予定年齢", min_value=int(current_age)+1, max_value=80, value=65, step=1)
    with col3:
        life_expectancy = st.number_input("想定寿命", min_value=65, max_value=100, value=85, step=1)

    col1, col2 = st.columns(2)
    with col1:
        years_as_director = st.number_input(
            "役員在任年数（引退時点）", min_value=1, max_value=50,
            value=int(retire_age - current_age + 10), step=1,
            help="退職所得控除・役員退職金の計算に使います。"
        )
    with col2:
        num_heirs = st.number_input(
            "法定相続人の数", min_value=1, max_value=10, value=2, step=1,
            help="生命保険の相続税非課税枠（500万円×人数）の計算に使います。"
        )

    st.divider()
    st.markdown("#### 💴 役員報酬・年金")
    col1, col2, col3 = st.columns(3)
    with col1:
        last_salary = st.number_input(
            "最終報酬月額（円）", min_value=0, max_value=5_000_000, value=1_000_000, step=50_000,
            format="%d", help="役員退職金の功績倍率方式に使います。"
        )
    with col2:
        monthly_pension = st.number_input(
            "公的年金 月額（円）", min_value=0, max_value=500_000, value=150_000, step=5_000,
            format="%d", help="65歳以降に受け取れる老齢年金の月額（ねんきん定期便を参照）。"
        )
    with col3:
        monthly_expense = st.number_input(
            "引退後の月々の生活費（円）", min_value=0, max_value=2_000_000, value=300_000, step=10_000,
            format="%d"
        )

    st.divider()
    st.markdown("#### 🏦 終身保険（法人契約）")
    st.caption("終身保険は解約返戻金＝退職金原資・死亡保険金＝相続対策の両面で活用できます。")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        ins_monthly = st.number_input(
            "月額保険料（円）", min_value=0, max_value=5_000_000, value=200_000, step=10_000,
            format="%d", key="ins_monthly"
        )
    with col2:
        ins_years = st.number_input(
            "払込年数", min_value=1, max_value=40, value=int(retire_age - current_age), step=1,
            key="ins_years"
        )
    with col3:
        ins_return_rate = st.number_input(
            "解約返戻率（%）", min_value=0.0, max_value=120.0, value=90.0, step=1.0,
            help="引退時点での解約返戻率。保険設計書で確認してください。"
        )
    with col4:
        ins_death_benefit = st.number_input(
            "死亡保険金額（万円）", min_value=0, max_value=100_000, value=10_000, step=500,
            format="%d", help="万が一の際に法人が受け取る保険金額。"
        ) * 10_000

    st.markdown("##### 出口戦略を選択")
    exit_strategy = st.radio(
        "引退時の保険の扱い方",
        ["① 解約して退職金として受取", "② 現物支給（法人→本人へ名義変更）", "③ 後継者へ名義変更"],
        help="""
① 法人が解約し、解約返戻金を役員退職金として支給（退職所得控除が使える）
② 保険契約ごと経営者個人に名義変更。個人で継続し将来の保険金・解約金を受取（低解約返戻期間中の変更が節税のカギ）
③ 後継者に名義変更し、事業承継・後継者の退職金積立として継続活用
        """
    )

    st.divider()
    st.markdown("#### 🏛️ 小規模企業共済")
    col1, col2 = st.columns(2)
    with col1:
        kyosai_monthly = st.number_input(
            "掛金月額（円）※最大70,000円", min_value=0, max_value=70_000, value=70_000, step=1_000,
            format="%d"
        )
    with col2:
        kyosai_years = st.number_input(
            "加入年数（引退時点）", min_value=0, max_value=45, value=int(retire_age - current_age), step=1,
            key="kyosai_years"
        )

    st.divider()
    st.markdown("#### 📈 iDeCo（個人型確定拠出年金）")
    col1, col2, col3 = st.columns(3)
    with col1:
        ideco_monthly = st.number_input(
            "掛金月額（円）※経営者最大23,000円", min_value=0, max_value=23_000, value=23_000, step=1_000,
            format="%d"
        )
    with col2:
        ideco_years = st.number_input(
            "加入年数（引退時点）", min_value=0, max_value=40, value=int(retire_age - current_age), step=1,
            key="ideco_years"
        )
    with col3:
        ideco_return = st.number_input(
            "想定運用利率（%）", min_value=0.0, max_value=10.0, value=3.0, step=0.5
        )

    st.divider()
    st.markdown("#### 🏆 役員退職金の設計")
    col1, col2 = st.columns(2)
    with col1:
        multiplier = st.number_input(
            "功績倍率", min_value=0.5, max_value=3.0, value=2.0, step=0.1,
            help="一般的に代表取締役：2.0〜3.0倍、取締役：1.5〜2.0倍が目安。税務上の適正額に注意。"
        )
    with col2:
        st.markdown(f"""
<div style="background:#eef4ff;border-radius:8px;padding:12px 16px;margin-top:8px;">
役員退職金の適正額（目安）<br>
<strong style="font-size:1.3rem;">
{calc_yakuin_taishokukin(last_salary, years_as_director, multiplier)/10000:,.0f}万円
</strong><br>
<small>= 月額{last_salary:,}円 × {years_as_director}年 × {multiplier}倍</small>
</div>
""", unsafe_allow_html=True)

    st.divider()
    st.markdown("#### 🎯 理想の老後設定")
    col1, col2 = st.columns(2)
    with col1:
        ideal_monthly_income = st.number_input(
            "引退後に欲しい月収（円）", min_value=0, max_value=2_000_000, value=500_000, step=10_000,
            format="%d", help="年金＋資産取り崩しで実現したい月々の手取り収入。"
        )
    with col2:
        ideal_asset_at_death = st.number_input(
            "死亡時に残したい資産（万円）", min_value=0, max_value=100_000, value=3_000, step=500,
            format="%d", help="相続・遺族への資産として残したい金額。"
        ) * 10_000

    st.divider()
    run_btn = st.button("🔍 シミュレーション実行", type="primary", use_container_width=True)
    if run_btn:
        st.session_state["simulated"] = True

if not st.session_state.get("simulated"):
    st.info("👆 上のフォームに情報を入力し、「シミュレーション実行」ボタンを押してください。")
    with st.expander("📖 主な用語の説明"):
        st.markdown("""
| 用語 | 説明 |
|------|------|
| **終身保険（法人契約）** | 法人が契約者・保険料負担者、経営者が被保険者。解約返戻金を退職金原資に、死亡保険金を相続対策に活用 |
| **解約返戻率** | 払い込んだ保険料に対して解約時に戻ってくる割合。90%なら保険料の90%が戻る |
| **現物支給（名義変更）** | 法人から個人へ保険契約ごと譲渡。低解約返戻期間中に行うと節税効果大 |
| **小規模企業共済** | 経営者の退職金制度。掛金全額が所得控除。月最大7万円 |
| **功績倍率方式** | 役員退職金の計算式：最終報酬月額×勤続年数×功績倍率 |
| **退職所得控除** | 勤続年数に応じて退職金から差し引かれる控除額。長期在任ほど有利 |
| **iDeCo** | 個人型確定拠出年金。法人経営者は月最大2.3万円。掛金全額所得控除 |
        """)
    st.stop()

# ─────────────────────────────────────────
# 計算実行
# ─────────────────────────────────────────
ins = calc_seimei(ins_monthly, ins_years, ins_return_rate, ins_death_benefit)
kyosai = calc_kyosai(kyosai_monthly, kyosai_years)
ideco = calc_ideco(ideco_monthly, ideco_years, ideco_return)
yakuin = calc_yakuin_taishokukin(last_salary, years_as_director, multiplier)

# 退職金総額（出口戦略による）
if exit_strategy == "① 解約して退職金として受取":
    retirement_total = ins["解約返戻金（概算）"] + kyosai["受取概算額"] + ideco["積立総額（運用込）"]
    retirement_detail_label = "解約返戻金"
    exit_note = "終身保険を解約し、解約返戻金を退職金として受け取ります。退職所得控除が適用されます。"
elif exit_strategy == "② 現物支給（法人→本人へ名義変更）":
    # 現物支給の場合、保険は個人が継続。名義変更時の経済的利益に注意
    retirement_total = kyosai["受取概算額"] + ideco["積立総額（運用込）"]
    retirement_detail_label = "名義変更（現物支給）"
    exit_note = "保険契約ごと個人に名義変更。保険は個人で継続できます。名義変更時点の解約返戻金相当額が経済的利益として課税される場合があります。"
elif exit_strategy == "③ 後継者へ名義変更":
    retirement_total = kyosai["受取概算額"] + ideco["積立総額（運用込）"]
    retirement_detail_label = "後継者へ承継"
    exit_note = "保険を後継者に名義変更し、事業承継と後継者の退職金積立を兼ねます。"

# 退職所得控除・税金計算
ret_tax = calc_retirement_tax(retirement_total, years_as_director)

# 相続税非課税枠
inheritance_exemption = LIFE_INSURANCE_INHERITANCE_EXEMPTION * num_heirs

# 老後キャッシュフロー
pension_start_age = max(retire_age, 65)
cf_df = calc_cashflow(
    retire_age=pension_start_age,
    life_expectancy=life_expectancy,
    net_retirement=ret_tax["実質手取り"],
    monthly_pension=monthly_pension,
    monthly_expense=monthly_expense,
)

# 資産がゼロになる年齢
depleted_ages = cf_df[cf_df["資産残高"] <= 0]["年齢"].tolist()
depleted_age = depleted_ages[0] if depleted_ages else None

# ギャップ分析
required_total = ideal_monthly_income * 12 * (life_expectancy - retire_age)
pension_total = monthly_pension * 12 * (life_expectancy - pension_start_age)
gap = required_total - pension_total - ret_tax["実質手取り"]

# ─────────────────────────────────────────
# [1] 総合サマリー
# ─────────────────────────────────────────
st.markdown("## 💡 老後資金シミュレーション結果")

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown(f"""
<div class="main-box">
  <h2>🏆 引退時の退職金（実質手取り）</h2>
  <div style="font-size:2rem; font-weight:900; color:#ffe066;">
    約{ret_tax["実質手取り"]/10000:,.0f}万円
  </div>
  <div style="font-size:0.95rem; line-height:2.0; margin-top:8px;">
    退職金総額：{retirement_total/10000:,.0f}万円<br>
    退職所得控除：▼{ret_tax["退職所得控除額"]/10000:,.0f}万円<br>
    税金合計：▼{ret_tax["税金合計"]/10000:,.0f}万円
    （実効税率 {ret_tax["実効税率"]:.1f}%）
  </div>
</div>
""", unsafe_allow_html=True)

with col2:
    death_benefit = ins["死亡保険金額"]
    st.markdown(f"""
<div class="main-box">
  <h2>🛡️ 万が一の場合・相続対策</h2>
  <div style="font-size:2rem; font-weight:900; color:#ffe066;">
    死亡保険金 {death_benefit/10000:,.0f}万円
  </div>
  <div style="font-size:0.95rem; line-height:2.0; margin-top:8px;">
    相続税非課税枠：{inheritance_exemption/10000:,.0f}万円<br>
    （500万円 × {num_heirs}人）<br>
    課税対象外の保険金：最大{min(death_benefit, inheritance_exemption)/10000:,.0f}万円
  </div>
</div>
""", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────
# [2] ギャップ分析・対策提案
# ─────────────────────────────────────────
st.markdown("## 📊 現状診断・ギャップ分析")

col1, col2, col3 = st.columns(3)
col1.metric("必要老後資金（総額）", f"{required_total/10000:,.0f}万円",
            help=f"希望月収{ideal_monthly_income/10000:.0f}万円 × 12ヶ月 × {life_expectancy - retire_age}年")
col2.metric("準備できている資金", f"{(ret_tax['実質手取り'] + pension_total)/10000:,.0f}万円",
            help="退職金手取り＋公的年金の合計")
col3.metric("不足額", f"{max(0, gap)/10000:,.0f}万円" if gap > 0 else "余剰あり",
            delta=f"{'▼' if gap > 0 else '▲'}{abs(gap)/10000:,.0f}万円",
            delta_color="inverse" if gap > 0 else "normal")

# 資産寿命
if depleted_age:
    st.markdown(f"""
<div class="gap-box">
⚠️ <strong>資産が尽きる年齢：{depleted_age}歳</strong>
想定寿命{life_expectancy}歳まで <strong>あと{life_expectancy - depleted_age}年分</strong> の資金が不足しています。
</div>
""", unsafe_allow_html=True)
else:
    st.markdown(f"""
<div class="ok-box">
✅ <strong>想定寿命{life_expectancy}歳まで資産が持続します。</strong>
{life_expectancy}歳時点の残資産：約{cf_df.iloc[-1]["資産残高"]/10000:,.0f}万円
</div>
""", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────
# [3] 対策提案
# ─────────────────────────────────────────
st.markdown("## 💡 理想に近づくための対策提案")

proposals = []

# 小規模共済の提案
if kyosai_monthly < 70_000:
    diff = 70_000 - kyosai_monthly
    add_receive = int(diff * 12 * kyosai_years * 1.15)
    add_tax = int(diff * 12 * 0.30 * kyosai_years)
    proposals.append({
        "優先度": "🔴 高",
        "提案": f"小規模企業共済の掛金を月{diff:,}円増額して満額（7万円）にする",
        "効果": f"受取額が約{add_receive/10000:.0f}万円増加・節税額が約{add_tax/10000:.0f}万円増加",
    })

# 終身保険の提案
if ins_monthly < 100_000:
    proposals.append({
        "優先度": "🔴 高",
        "提案": "終身保険の保険料を増額して解約返戻金（退職金原資）を拡大する",
        "効果": f"保険料を月10万円増額すると{ins_years}年後の解約返戻金が約{int(100_000*12*ins_years*ins_return_rate/100)/10000:.0f}万円追加",
    })

# iDeCoの提案
if ideco_monthly < 23_000:
    diff_ideco = 23_000 - ideco_monthly
    proposals.append({
        "優先度": "🟡 中",
        "提案": f"iDeCoを月{diff_ideco:,}円増額して上限（2.3万円）まで活用する",
        "効果": f"年間節税額が約{int(diff_ideco*12*0.30/10000)}万円増加",
    })

# 引退年齢の提案
if depleted_age and depleted_age < life_expectancy:
    shortage_years = life_expectancy - depleted_age
    proposals.append({
        "優先度": "🔴 高",
        "提案": f"引退を{min(3, shortage_years)}年延ばして{retire_age + min(3, shortage_years)}歳にする",
        "効果": f"在任年数が増え退職所得控除が拡大。退職金積立期間も延長できる",
    })

# 出口戦略の提案
if exit_strategy == "① 解約して退職金として受取":
    proposals.append({
        "優先度": "🟡 中",
        "提案": "保険の現物支給（名義変更）も検討する",
        "効果": "個人で保険を継続でき、将来の死亡保険金を相続対策として活用できる。低解約返戻期間中の変更が節税のカギ",
    })

# 役員退職金の提案
if yakuin > retirement_total * 0.5:
    proposals.append({
        "優先度": "🟢 情報",
        "提案": "役員退職金の財源確保を確認する",
        "効果": f"功績倍率方式による適正退職金額は約{yakuin/10000:,.0f}万円。財源（保険・現預金）が十分か確認を",
    })

if proposals:
    df_prop = pd.DataFrame(proposals)
    st.dataframe(df_prop, use_container_width=True, hide_index=True)
else:
    st.success("現在の設定で理想の老後資金が準備できています！引き続き継続しましょう。")

st.divider()

# ─────────────────────────────────────────
# [4] 各制度の詳細
# ─────────────────────────────────────────
st.markdown("## 📋 各制度の詳細試算")

tab1, tab2, tab3, tab4 = st.tabs(["🏦 終身保険", "🏛️ 小規模企業共済", "📈 iDeCo", "🏆 役員退職金・控除"])

with tab1:
    st.markdown(f"**出口戦略：{exit_strategy}**")
    st.info(exit_note)
    col1, col2, col3 = st.columns(3)
    col1.metric("保険料総額", f"{ins['保険料総額']/10000:,.0f}万円")
    col2.metric("解約返戻金（概算）", f"{ins['解約返戻金（概算）']/10000:,.0f}万円")
    col3.metric("死亡保険金", f"{ins['死亡保険金額']/10000:,.0f}万円")
    col1.metric("年間節税額（概算）", f"{ins['年間節税額（損金1/2・概算）']/10000:.1f}万円")
    col2.metric("節税総額（概算）", f"{ins['節税総額（概算）']/10000:.0f}万円")
    col3.metric("相続税非課税枠", f"{inheritance_exemption/10000:,.0f}万円")

    st.markdown("""
<div class="warn-box">
⚠️ <strong>終身保険の損金算入について</strong><br>
終身保険（最高解約返戻率70%超）は原則として保険期間の前半は資産計上・後半は損金算入となります。
設計書の内容をもとに税理士・保険担当者と確認してください。
</div>
""", unsafe_allow_html=True)

with tab2:
    col1, col2, col3 = st.columns(3)
    col1.metric("掛金総額", f"{kyosai['掛金総額']/10000:,.0f}万円")
    col2.metric("受取概算額", f"{kyosai['受取概算額']/10000:,.0f}万円")
    col3.metric("増加額", f"{(kyosai['受取概算額']-kyosai['掛金総額'])/10000:,.0f}万円")
    col1.metric("年間節税額（概算）", f"{kyosai['年間節税額（概算）']/10000:.1f}万円")
    col2.metric("節税総額（概算）", f"{kyosai['節税総額（概算）']/10000:.0f}万円")
    col3.metric("加入年数", f"{kyosai['加入年数']}年")
    st.caption("※受取額は共済金額表に基づく概算です。実際の受取額は中小機構にお問い合わせください。")

with tab3:
    col1, col2, col3 = st.columns(3)
    col1.metric("掛金総額", f"{ideco['掛金総額']/10000:,.0f}万円")
    col2.metric("積立総額（運用込）", f"{ideco['積立総額（運用込）']/10000:,.0f}万円")
    col3.metric("運用益", f"{ideco['運用益']/10000:,.0f}万円")
    col1.metric("年間節税額（概算）", f"{ideco['年間節税額（概算）']/10000:.1f}万円")
    col2.metric("節税総額（概算）", f"{ideco['節税総額（概算）']/10000:.0f}万円")
    col3.metric("想定運用利率", f"{ideco_return}%")
    st.caption("※iDeCoの受取時は退職所得控除または公的年金等控除が適用されます。")

with tab4:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**役員退職金（功績倍率方式）**")
        st.metric("適正退職金額（目安）", f"{yakuin/10000:,.0f}万円",
                  help=f"月額{last_salary:,}円 × {years_as_director}年 × {multiplier}倍")
    with col2:
        st.markdown("**退職所得控除・税金計算**")

    tax_data = {
        "項目": ["退職金総額", "退職所得控除額", "課税対象（控除後÷2）",
                 "所得税（復興税込）", "住民税", "税金合計", "実質手取り"],
        "金額": [
            f"{ret_tax['退職金総額']/10000:,.0f}万円",
            f"▼{ret_tax['退職所得控除額']/10000:,.0f}万円",
            f"{ret_tax['課税対象額（控除後÷2）']/10000:,.0f}万円",
            f"▼{ret_tax['所得税（復興税込）']/10000:,.1f}万円",
            f"▼{ret_tax['住民税']/10000:,.1f}万円",
            f"▼{ret_tax['税金合計']/10000:,.0f}万円",
            f"✅ {ret_tax['実質手取り']/10000:,.0f}万円",
        ]
    }
    st.dataframe(pd.DataFrame(tax_data), use_container_width=True, hide_index=True)

    with st.expander("📐 退職所得控除の計算式"):
        st.markdown(f"""
**勤続年数：{years_as_director}年の場合**

{'20年以下：40万円 × ' + str(years_as_director) + '年' if years_as_director <= 20 else '20年超：800万円 ＋ 70万円 × (' + str(years_as_director) + '年 − 20年)'}

= **{ret_tax['退職所得控除額']/10000:,.0f}万円**

| 勤続年数 | 控除額の計算式 |
|---------|-------------|
| 20年以下 | 40万円 × 勤続年数（最低80万円） |
| 20年超 | 800万円 ＋ 70万円 × （勤続年数 − 20年） |
        """)

st.divider()

# ─────────────────────────────────────────
# [5] 老後キャッシュフロー
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
if ideal_asset_at_death > 0:
    fig.add_hline(y=ideal_asset_at_death / 10000, line_color="green",
                  line_dash="dash", line_width=1.5,
                  annotation_text=f"残したい資産:{ideal_asset_at_death/10000:,.0f}万円",
                  annotation_position="right")

fig.update_layout(
    title="引退後の資産残高の推移",
    xaxis_title="年齢",
    yaxis_title="資産残高（万円）",
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(size=13),
    height=400,
)
fig.update_yaxes(gridcolor="#e9ecef")
fig.update_xaxes(gridcolor="#e9ecef")
st.plotly_chart(fig, use_container_width=True)

st.dataframe(
    cf_df.style.applymap(
        lambda v: "color: red; font-weight: bold" if isinstance(v, (int, float)) and v < 0 else "",
        subset=["資産残高", "年間収支"]
    ),
    use_container_width=True, hide_index=True
)

# ─────────────────────────────────────────
# フッター
# ─────────────────────────────────────────
st.markdown("""
---
<div style="font-size:0.8rem; color:#6c757d; text-align:center;">
⚠️ <strong>免責事項</strong>：本シミュレーターは概算値の提供を目的としており、実際の税額・受取額は個人の状況により異なります。
保険・税務・法律に関する最終判断は、税理士・社会保険労務士・ファイナンシャルプランナー・保険担当者にご相談ください。<br>
退職所得控除は2024年度税制に基づきます。小規模企業共済の受取額は概算です。
</div>
""", unsafe_allow_html=True)
