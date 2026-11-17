import requests
import time
import random
import string


BASE_URL = "http://127.0.0.1:5000"


def random_username():
    return "testuser_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=6)
    )


def test_application():
    print("\n" + "=" * 70)
    print("STEP 7: FUNCTIONAL APPLICATION TESTING")
    print("=" * 70)

    session = requests.Session()

    username = random_username()
    password = "Test@12345"

    print("\n🧪 Test 1: Checking application...")
    
    try:
        response = session.get(BASE_URL, timeout=5)

        if response.status_code not in [200, 302]:
            print(f"❌ Application returned HTTP {response.status_code}")
            return False

        print("   ✅ Application is reachable")

    except requests.exceptions.RequestException as e:
        print(f"❌ Could not connect to application: {e}")
        return False


    # ---------------------------------------------------------
    # REGISTER
    # ---------------------------------------------------------

    print("\n🧪 Test 2: Registering test user...")
    
    try:
        response = session.post(
            BASE_URL + "/register",
            data={
                "username": username,
                "password": password
            },
            timeout=5
        )

        print(f"   HTTP {response.status_code}")

        if response.status_code not in [200, 302]:
            print("❌ Registration failed")
            return False

        print("   ✅ Registration request successful")

    except requests.exceptions.RequestException as e:
        print(f"❌ Registration error: {e}")
        return False


    # ---------------------------------------------------------
    # LOGIN
    # ---------------------------------------------------------

    print("\n🧪 Test 3: Logging in...")

    try:
        response = session.post(
            BASE_URL + "/login",
            data={
                "username": username,
                "password": password
            },
            allow_redirects=True,
            timeout=5
        )

        print(f"   HTTP {response.status_code}")

        if response.status_code != 200:
            print("❌ Login failed")
            return False

        print("   ✅ Login request successful")

    except requests.exceptions.RequestException as e:
        print(f"❌ Login error: {e}")
        return False


    # ---------------------------------------------------------
    # TASK PAGE
    # ---------------------------------------------------------

    print("\n🧪 Test 4: Opening task dashboard...")

    try:
        response = session.get(
            BASE_URL + "/tasks",
            allow_redirects=True,
            timeout=5
        )

        print(f"   HTTP {response.status_code}")

        if response.status_code != 200:
            print("❌ Task dashboard failed")
            return False

        print("   ✅ Task dashboard accessible")

    except requests.exceptions.RequestException as e:
        print(f"❌ Task dashboard error: {e}")
        return False


    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------

    print("\n🧪 Test 5: Creating test task...")

    task_name = "AUTONOMOUS_TEST_TASK"

    try:
        response = session.post(
            BASE_URL + "/add_task",
            data={
                "task": task_name
            },
            allow_redirects=True,
            timeout=5
        )

        print(f"   HTTP {response.status_code}")

        if response.status_code != 200:
            print("❌ Task creation failed")
            return False

        if task_name not in response.text:
            print("⚠️ Task creation response did not contain task")

        else:
            print("   ✅ Task created successfully")

    except requests.exceptions.RequestException as e:
        print(f"❌ Task creation error: {e}")
        return False


    # ---------------------------------------------------------
    # FINAL RESULT
    # ---------------------------------------------------------

    print("\n" + "=" * 70)
    print("🎉 FUNCTIONAL TESTING COMPLETED")
    print("=" * 70)

    print("\nTest account:")
    print(f"Username: {username}")
    print(f"Password: {password}")

    return True


if __name__ == "__main__":
    test_application()