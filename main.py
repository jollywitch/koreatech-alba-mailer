import os
import sqlite3
import smtplib
import requests
from lxml import html
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

PORTAL_URL = "https://portal.koreatech.ac.kr"

def login(user_id: str, user_pwd: str):
    session = requests.Session()
    # 세션을 사용하면 쿠키 자동 유지됨

    # 1. 첫 번째 요청
    resp1 = session.post(
        f"{PORTAL_URL}/sso/sso_login.jsp",
        data={
            "user_id": user_id,
            "user_pwd": user_pwd,
            "RelayState": "/index.jsp",
            "id": "PORTAL",
            "targetId": "PORTAL",
            "user_password": user_pwd,
        }
    )
    print("Step 1:", resp1.status_code)

    # 2. 두 번째 요청
    resp2 = session.post(
        f"{PORTAL_URL}/ktp/login/checkLoginId.do",
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        },
        data={
            "login_id": user_id,
            "login_pwd": user_pwd,
            "login_type": "",
            "login_empno": "",
            "login_certDn": "",
            "login_certChannel": "",
        }
    )
    print("Step 2:", resp2.status_code)

    # 3. 세 번째 요청
    resp3 = session.post(
        f"{PORTAL_URL}/ktp/login/checkSecondLoginCert.do",
        data={"login_id": user_id}
    )
    print("Step 3:", resp3.status_code)

    # 4. 수동 쿠키 추가 (필요하다면)
    session.cookies.set(
        "kut_login_type", "id",
        domain="koreatech.ac.kr", path="/"
    )

    # 5. 마지막 요청 및 리다이렉션 처리
    url = f"{PORTAL_URL}/exsignon/sso/sso_assert.jsp"
    data = {
        "certUserId": "",
        "certLoginId": "",
        "certEmpNo": "",
        "certType": "",
        "secondCert": "",
        "langKo": "",
        "langEn": ""
    }

    resp = session.post(url, data=data, allow_redirects=False)
    print("Step 5:", resp.status_code)

    # 연속적인 manual redirection 처리
    while resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
        next_url = resp.headers.get("Location")
        if not next_url:
            break
        # 절대경로 보정
        if next_url.startswith("/"):
            next_url = PORTAL_URL + next_url
        print("Redirect to:", next_url)
        resp = session.get(next_url, allow_redirects=False)

    print("최종 상태 코드:", resp.status_code)
    print("최종 URL:", resp.url)

    return session  # 로그인된 세션 반환

def init_db(db_path="processed_posts.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            post_id TEXT PRIMARY KEY
        )
    """)
    conn.commit()
    
    return conn

def get_new_posts(conn, posts):
    cursor = conn.cursor()
    new_posts = {}

    for post_id, title in posts.items():
        cursor.execute("SELECT 1 FROM posts WHERE post_id = ?", (post_id,))
        if cursor.fetchone() is None:
            new_posts[post_id] = title
            cursor.execute("INSERT INTO posts (post_id) VALUES (?)", (post_id,))
    
    conn.commit()

    return new_posts

def get_posts(resp: str):
    tree = html.fromstring(resp)
    posts = {}
    rows = tree.xpath('//tr[@data-name="post_list"]')

    for row in rows:
        post_id = row.xpath('.//td[contains(@class,"bc-s-post_seq")]/text()')
        post_id = post_id[0].strip() if post_id else None
        if not post_id:
            continue

        title = row.xpath('.//td[contains(@class,"bc-s-title")]//span/text()')
        title = title[0].strip() if title else ""

        posts[post_id] = title
    
    return posts

def get_new_posts(conn, posts):
    cursor = conn.cursor()
    new_posts = {}

    for post_id, title in posts.items():
        cursor.execute("SELECT 1 FROM posts WHERE post_id = ?", (post_id,))
        if cursor.fetchone() is None:  # DB에 없는 글이면 새 글
            new_posts[post_id] = title
            cursor.execute("INSERT INTO posts (post_id) VALUES (?)", (post_id,))
    
    conn.commit()

    return new_posts

def send_email(subject: str, body: str, receiver: str):
    sender = "no-reply@jollywit.ch"  # Postfix에서 발송 가능한 주소
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subject
    msg.attach(MIMEText(body, "plain"))

    # Postfix를 로컬 SMTP 서버로 사용
    with smtplib.SMTP('localhost', 25) as server:
        server.sendmail(sender, receiver, msg.as_string())


if __name__ == "__main__":
    load_dotenv()
    conn = init_db()
    USER_ID = os.getenv("USER_ID")
    USER_PWD = os.getenv("USER_PW")
    KEYWORDS = ["알바", "아르바이트"]
    session = login(USER_ID, USER_PWD)
    resp = session.get("https://portal.koreatech.ac.kr/ctt/bb/bulletin?b=21")

    new_posts = get_new_posts(conn, get_posts(resp.text))
    
    filtered_posts = {
        post_id: title
        for post_id, title in new_posts.items()
        if any(keyword in title for keyword in KEYWORDS)
    }

    if filtered_posts:
        body = "\n".join([f"{post_id} : {title}" for post_id, title in filtered_posts.items()])
        send_email("새 게시글 알림", body, "augustapple77@gmail.com")
