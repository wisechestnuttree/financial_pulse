import pymysql
import os
from dotenv import load_dotenv
from logs.logger import getLogger

# 1. .env 파일 로드
# current_dir = os.path.dirname(os.path.abspath(__file__))
# env_path = os.path.normpath(os.path.join(current_dir, "..", ".env"))
# load_dotenv(env_path)
load_dotenv()

logger = getLogger("system")

def getConn():
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        db=os.getenv("DB_NAME"),
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn

def createTables():
    # 2. DB 연결 설정
    conn = getConn()

    try:
        with conn.cursor() as cursor:
            # 3. 테이블 생성 쿼리 (순서 중요: user가 먼저!)
            queries = [
                """
                CREATE TABLE IF NOT EXISTS user (
                    u_id INT AUTO_INCREMENT PRIMARY KEY,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    encry_pw VARCHAR(255) NOT NULL,
                    name VARCHAR(50) NOT NULL,
                    phone_num VARCHAR(100) NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS userInterests (
                    u_id INT NOT NULL,
                    inter_id INT,
                    interested VARCHAR(100),
                    CONSTRAINT fk_user_interests FOREIGN KEY (u_id) REFERENCES user(u_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """,
                """
                CREATE TABLE IF NOT EXISTS loginFail (
                    u_id INT NOT NULL,
                    dateFail DATETIME NOT NULL,
                    CONSTRAINT fk_user_login_fail FOREIGN KEY (u_id) REFERENCES user(u_id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """,
                """
                CREATE TABLE IF NOT EXISTS retryQueue (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    url         VARCHAR(2048) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            ]

            for query in queries:
                cursor.execute(query)

            conn.commit()
            logger.info("DB: 생성 완료", extra={"action": "db"})

    except Exception as e:
        logger.error(f"DB: 생성 실패({e})", extra={"action": "db", "err_msg": str(e)})
    finally:
        conn.close()


if __name__ == "__main__":
    createTables()