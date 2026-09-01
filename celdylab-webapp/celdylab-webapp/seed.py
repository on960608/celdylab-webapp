"""
최초 1회 실행: DB 테이블을 만들고, 기본 브랜드/제품 목록과 데모 계정을 넣어줘요.

사용법:
    python3 seed.py
"""
import sys
from werkzeug.security import generate_password_hash
import db

ARCHIVE_DATA = [
    ("코드니처", ["텀블러 전용 클리너", "싹캐처", "2중압축 베개 세탁망", "노잔여 텀블러 세정제", "세제톡 버블 클리너", "하수구 세정서버", "변기수조 세정서버"]),
    ("빠이러스", ["가글캔디", "꽃가글"]),
    ("명퉤", ["길운오행염주", "학업성취 금부적", "부귀재물비방", "액막이명퉤", "플래그십 스토어"]),
    ("라이프스타일", ["제습서버v2"]),
]


def main():
    db.init_db()

    # 브랜드/제품 폴더 자리 만들기 (링크는 비워둠 - 로그인 후 웹앱에서 직접 채우면 됨)
    for brand, products in ARCHIVE_DATA:
        db.upsert_archive_link(brand, "", "", "seed")
        for p in products:
            db.upsert_archive_link(brand, p, "", "seed")
    print(f"자료실: 브랜드 {len(ARCHIVE_DATA)}개, 제품 {sum(len(p) for _, p in ARCHIVE_DATA)}개 준비 완료")

    # 데모 계정 (반드시 로그인 후 비밀번호를 바꾸거나, add_employee.py로 실제 직원 계정을 새로 만들어주세요)
    existing = db.get_employee_by_username("admin")
    if not existing:
        db.create_employee("admin", generate_password_hash("celdylab2026"), "관리자(데모)")
        print("데모 계정 생성: username=admin / password=celdylab2026  (꼭 바꿔주세요!)")
    else:
        print("데모 계정(admin)이 이미 있어요 — 건너뜀")


if __name__ == "__main__":
    main()
