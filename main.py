"""
어제의 일별 박스오피스를 보여주는 스트림릿 앱
- 데이터 출처: KOBIS(영화진흥위원회) 일별 박스오피스 오픈API
- 인증키는 st.secrets["KOBIS_KEY"]에서 불러옵니다. (코드에 직접 쓰지 않음)
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


def get_yesterday_kst() -> str:
    """
    한국 시간(KST) 기준으로 '어제' 날짜를 yyyymmdd 형식으로 반환합니다.
    배포 서버의 시계가 한국 시간이 아니어도 항상 한국 기준 '어제'를 계산합니다.
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# ---------------------------------------------------------
# API 호출 함수
# 같은 날짜(target_dt)로 다시 요청하면 1시간 동안은 캐시된 결과를 그대로 씁니다.
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_box_office(target_dt: str, api_key: str):
    """
    KOBIS API를 호출해서 (성공 여부, 데이터 또는 에러메시지)를 돌려줍니다.
    반환값 형태: (True, DataFrame) 또는 (False, "에러 메시지")
    """
    params = {"key": api_key, "targetDt": target_dt}

    # 1) 네트워크 요청 자체가 실패하는 경우 (인터넷 문제, 타임아웃 등)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return False, f"KOBIS 서버에 접속하지 못했습니다. 인터넷 연결 또는 API 주소를 확인해 주세요. (상세: {e})"

    # 2) 응답이 JSON 형식이 아닌 경우 (응답 상태코드는 200이어도 내용이 깨질 수 있음)
    try:
        data = response.json()
    except ValueError:
        return False, "KOBIS 서버 응답을 해석할 수 없습니다(JSON 형식이 아님). 잠시 후 다시 시도해 주세요."

    # 3) 인증키가 틀리는 등 오류가 있을 때는 faultInfo 상자가 옵니다.
    if "faultInfo" in data:
        message = data["faultInfo"].get("message", "알 수 없는 오류")
        return False, f"API에서 오류를 반환했습니다: {message}\n→ secrets.toml의 KOBIS_KEY 값이 올바른지 확인해 주세요."

    # 4) 정상 구조인지 확인
    box_office_result = data.get("boxOfficeResult")
    if box_office_result is None:
        return False, "응답에 boxOfficeResult가 없습니다. API 응답 구조가 문서와 다른지 확인해 주세요."

    movie_list = box_office_result.get("dailyBoxOfficeList", [])
    if not movie_list:
        return False, f"{target_dt} 날짜의 박스오피스 데이터가 비어 있습니다. 날짜를 확인하거나 잠시 후 다시 시도해 주세요."

    # 5) 데이터프레임으로 변환 + 숫자 컬럼 형변환 (원본은 전부 문자열로 옴)
    df = pd.DataFrame(movie_list)
    numeric_cols = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 순위 기준으로 정렬 (문자열이 아니라 숫자 기준으로 정확히 정렬됨)
    df = df.sort_values("rank").reset_index(drop=True)

    return True, df


# ---------------------------------------------------------
# 화면 구성
# ---------------------------------------------------------
def main():
    st.title("🎬 어제의 일별 박스오피스")

    # secrets에서 인증키 불러오기
    api_key = st.secrets.get("KOBIS_KEY")
    if not api_key:
        st.error("secrets에 KOBIS_KEY가 설정되어 있지 않습니다. Streamlit Cloud의 Settings → Secrets에 KOBIS_KEY를 등록해 주세요.")
        return

    target_dt = get_yesterday_kst()
    st.caption(f"조회 기준 날짜(한국시간 어제): {target_dt}")

    with st.spinner("박스오피스 데이터를 불러오는 중..."):
        success, result = fetch_box_office(target_dt, api_key)

    # 실패 시: 빈 화면 대신 안내 메시지를 보여주고 종료
    if not success:
        st.error(result)
        return

    df = result

    # ---- 1위 영화 지표 카드 3장 ----
    top_movie = df.iloc[0]
    st.subheader(f"🥇 1위: {top_movie['movieNm']}")
    col1, col2, col3 = st.columns(3)
    col1.metric("어제 관객수", f"{int(top_movie['audiCnt']):,}명")
    col2.metric("누적 관객수", f"{int(top_movie['audiAcc']):,}명")
    col3.metric("스크린수", f"{int(top_movie['scrnCnt']):,}개")

    st.divider()

    # ---- 관객수 상위 5편 막대그래프 ----
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    chart_df = top5.set_index("movieNm")[["audiCnt"]]
    st.bar_chart(chart_df)

    st.divider()

    # ---- 전체 순위표 ----
    st.subheader("📋 전체 순위표")
    display_df = df[["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
    display_df.columns = ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]
    # 보기 좋게 천단위 콤마 표시
    for col in ["관객수", "누적관객", "스크린수"]:
        display_df[col] = display_df[col].map(lambda x: f"{int(x):,}")
    st.dataframe(display_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
