# Локальная сборка APK на Windows 10

Buildozer работает только в Linux. На Windows есть два варианта:

---

## Вариант 1: WSL 2 (рекомендуется)

### 1. Установить WSL 2

В PowerShell **от имени администратора**:

```powershell
wsl --install
```

Перезагрузите компьютер. После перезагрузки откроется Ubuntu (или выберите дистрибутив при установке).

### 2. Установить зависимости в Ubuntu (WSL)

Откройте Ubuntu из меню Пуск и выполните:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential git zip unzip openjdk-17-jdk \
  autoconf libtool libltdl-dev pkg-config \
  zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 \
  cmake libffi-dev libssl-dev automake lld ccache
```

### 3. Установить Python и Buildozer

```bash
sudo apt-get install -y python3 python3-pip python3-venv
pip install --upgrade pip
pip install "Cython==0.29.36" buildozer
```

### 4. Собрать APK

Перейдите в папку проекта (путь к Windows-диску в WSL: `/mnt/d/Projects/Python/Authenticator`):

```bash
cd /mnt/d/Projects/Python/Authenticator
buildozer -v android debug
```

Первый запуск загрузит Android SDK/NDK (~2–4 ГБ) — займёт 20–60 минут.

Готовый APK будет в `bin/*.apk`.

---

## Вариант 2: Docker

Если установлен Docker Desktop:

```powershell
cd D:\Projects\Python\Authenticator
docker run --rm -v "${PWD}:/src" -w /src kivy/buildozer buildozer -v android debug
```

Или используйте образ `kivy/buildozer` (проверьте актуальность на Docker Hub).

---

## Вариант 3: GitHub Actions (без локальной сборки)

У вас уже настроен workflow. Просто сделайте `git push` в `master` — APK соберётся на GitHub. Скачать можно в **Actions → последний workflow run → Artifacts**.

---

## Переменные окружения (опционально)

- `JAVA_HOME` — путь к JDK 17 (WSL: обычно `/usr/lib/jvm/java-17-openjdk-amd64`)
- При ошибках с Java: `export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64`
