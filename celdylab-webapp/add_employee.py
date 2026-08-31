"""
실제 직원 계정을 추가하는 작은 도구예요.

사용법:
    python3 add_employee.py <아이디> <이름>
    예) python3 add_employee.py hh 희현

실행하면 비밀번호를 입력하라고 물어봐요 (화면에 안 보이게 입력됨).
"""
import sys
import getpass
from werkzeug.security import generate_password_hash
import db

def main():
    if len(sys.argv) != 3:
        print("사용법: python3 add_employee.py <아이디> <이름>")
        sys.exit(1)
    username, name = sys.argv[1], sys.argv[2]

    if db.get_employee_by_username(username):
        print(f"이미 '{username}' 아이디가 있어요.")
        sys.exit(1)

    pw1 = getpass.getpass("비밀번호: ")
    pw2 = getpass.getpass("비밀번호 확인: ")
    if pw1 != pw2:
        print("비밀번호가 서로 달라요. 다시 시도해주세요.")
        sys.exit(1)
    if len(pw1) < 4:
        print("비밀번호가 너무 짧아요.")
        sys.exit(1)

    db.create_employee(username, generate_password_hash(pw1), name)
    print(f"'{name}'({username}) 계정을 만들었어요.")


if __name__ == "__main__":
    main()
