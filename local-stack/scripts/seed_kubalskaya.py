"""Засеивает Health OS данными пациента Кубальская И.В.
Запуск:    make seed-kub
Идемпотентно: повторный запуск не дублирует записи (проверка по ФИО + дате визита).
"""
import os
import sys
from datetime import date, datetime, timezone

import httpx

API = os.environ.get("BACKEND_URL", "http://backend:8000")
TZ_OFFSET = "+03:00"  # Europe/Simferopol


def _dt(date_str: str, time_str: str = "10:00:00") -> str:
    return f"{date_str}T{time_str}{TZ_OFFSET}"


def main():
    with httpx.Client(base_url=API, timeout=30) as c:
        # ── 1. Семья ─────────────────────────────────────────
        families = c.get("/families").json()
        fam = next((f for f in families if f["name"] == "Семья Кубальских"), None)
        if not fam:
            fam = c.post("/families", json={
                "name": "Семья Кубальских",
                "notes": "Базовая семья для пилота Health OS",
            }).json()
            print(f"✓ семья создана: {fam['id']}")
        else:
            print(f"= семья уже есть: {fam['id']}")

        # ── 2. Пациент ───────────────────────────────────────
        patients = c.get("/patients").json()
        kub = next((p for p in patients if p["full_name"] == "Кубальская И.В."), None)
        if not kub:
            kub = c.post("/patients", json={
                "family_id": fam["id"],
                "full_name": "Кубальская И.В.",
                "birth_date": "1959-01-05",
                "sex": "f",
                "chronic_summary": "НАЖБП. Артифакия OD. Подозрение на глаукому OS. Атеросклероз. Подозрение на ГБ.",
                "notes": "Лечащий врач: Плисс Е.С. (ООО «Центр восстановления зрения», Севастополь).",
            }).json()
            print(f"✓ пациент создан: {kub['id']}")
        else:
            print(f"= пациент уже есть: {kub['id']}")

        pid = kub["id"]

        # ── 3. Визиты ────────────────────────────────────────
        existing_visits = c.get("/visits", params={"patient_id": pid}).json()
        existing_dates = {v["visit_date"] for v in existing_visits}

        visits_seed = [
            {
                "visit_date": "2025-09-15", "visit_type": "УЗИ ОБП",
                "specialty": "gastro", "facility": "Медцентр (УЗИ)",
                "summary": "Стеатоз печени (НАЖБП). Желчный пузырь — без особенностей.",
                "diagnosis_codes": ["K76.0"],
            },
            {
                "visit_date": "2025-10-20", "visit_type": "Офтальмолог",
                "specialty": "ophth", "practitioner": "Плисс Е.С.",
                "facility": "ООО «Центр восстановления зрения», Севастополь",
                "summary": "OD: артифакия + ЗОСТ. OS: незрелая катаракта. ВГД OS 16.6 mmHg.",
            },
            {
                "visit_date": "2026-02-09", "visit_type": "Офтальмолог (контроль)",
                "specialty": "ophth", "practitioner": "Плисс Е.С.",
                "facility": "ООО «Центр восстановления зрения», Севастополь",
                "summary": "ВГД OS поднялось до 21.5 mmHg. Рекомендованы периметрия + гониоскопия + OCT ДЗН.",
                "next_visit_date": "2026-05-09",
            },
        ]
        visits_by_date = {}
        for v in visits_seed:
            if v["visit_date"] in existing_dates:
                vv = next(x for x in existing_visits if x["visit_date"] == v["visit_date"])
            else:
                vv = c.post("/visits", json={"patient_id": pid, **v}).json()
                print(f"✓ визит: {v['visit_date']} {v['visit_type']}")
            visits_by_date[v["visit_date"]] = vv["id"]

        # ── 4. Наблюдения ────────────────────────────────────
        existing_obs = c.get("/observations", params={"patient_id": pid}).json()
        seen = {(o["code"], o.get("body_site"), o["observed_at"][:10]) for o in existing_obs}

        observations = [
            # УЗИ ОБП 15.09.2025
            ("STEATOSIS", "Стеатоз печени", None, None, "выражен", None,
             "степень", _dt("2025-09-15"), visits_by_date["2025-09-15"], None, None),
            # Офтальмолог 20.10.2025
            ("VA_OD", "Visual acuity OD", "OD", 0.7, None, None, None,
             _dt("2025-10-20"), visits_by_date["2025-10-20"], 0.8, 1.0),
            ("VA_OS", "Visual acuity OS", "OS", 0.5, None, None, None,
             _dt("2025-10-20"), visits_by_date["2025-10-20"], 0.8, 1.0),
            ("IOP_OD", "ВГД OD", "OD", 14.2, None, "mmHg", None,
             _dt("2025-10-20"), visits_by_date["2025-10-20"], 10, 21),
            ("IOP_OS", "ВГД OS", "OS", 16.6, None, "mmHg", None,
             _dt("2025-10-20"), visits_by_date["2025-10-20"], 10, 21),
            # Офтальмолог 09.02.2026 (контроль)
            ("VA_OD", "Visual acuity OD", "OD", 0.7, None, None, None,
             _dt("2026-02-09"), visits_by_date["2026-02-09"], 0.8, 1.0),
            ("VA_OS", "Visual acuity OS", "OS", 0.4, None, None, None,
             _dt("2026-02-09"), visits_by_date["2026-02-09"], 0.8, 1.0),
            ("IOP_OD", "ВГД OD", "OD", 15.1, None, "mmHg", None,
             _dt("2026-02-09"), visits_by_date["2026-02-09"], 10, 21),
            ("IOP_OS", "ВГД OS", "OS", 21.5, None, "mmHg", None,
             _dt("2026-02-09"), visits_by_date["2026-02-09"], 10, 21),
        ]
        for code, name, side, vnum, vtext, unit, _extra, observed_at, vid, lo, hi in observations:
            key = (code, side, observed_at[:10])
            if key in seen:
                continue
            c.post("/observations", json={
                "patient_id": pid, "visit_id": vid,
                "code": code, "display_name": name, "body_site": side,
                "value_num": vnum, "value_text": vtext, "unit": unit,
                "ref_low": lo, "ref_high": hi, "observed_at": observed_at,
            })
            print(f"✓ наблюдение: {code} {side or ''} = {vnum or vtext}")

        # ── 5. Активные проблемы ─────────────────────────────
        existing_problems = c.get("/problems", params={"patient_id": pid}).json()
        existing_titles = {p["title"] for p in existing_problems}

        problems = [
            ("НАЖБП", "K76.0", "chronic", "medium", "2025-09-15", "2026-09-01", "NAFLD-11"),
            ("Артифакия OD + ЗОСТ", "H59.8", "active", "medium", "2024-06-01", "2026-06-15", "OPH-11"),
            ("Незрелая катаракта OS + подозрение на глаукому", "H40.0/H25.1", "suspect", "critical", "2025-10-20", "2026-05-09", "OPH-11"),
            ("Атеросклероз", "I70.9", "chronic", "medium", None, "2026-12-01", "ATH-12"),
            ("Подозрение на гипертоническую болезнь", "I10", "suspect", "medium", None, "2026-06-01", "HTN-9"),
        ]
        problem_ids = {}
        for title, icd, status, sev, onset, review, tpl in problems:
            if title in existing_titles:
                pr = next(p for p in existing_problems if p["title"] == title)
            else:
                pr = c.post("/problems", json={
                    "patient_id": pid, "title": title, "icd10": icd, "status": status,
                    "severity": sev, "onset_date": onset, "next_review_date": review,
                    "careplan_template": tpl,
                }).json()
                print(f"✓ проблема: {title}")
            problem_ids[title] = pr["id"]

        # ── 6. Личные задачи ─────────────────────────────────
        existing_tasks = c.get("/tasks", params={"patient_id": pid}).json()
        existing_task_titles = {t["title"] for t in existing_tasks}

        tasks = [
            ("Осмотр ретинолога OD с расширенным зрачком", "критический", "2026-05-09", "разово", None, problem_ids.get("Артифакия OD + ЗОСТ")),
            ("Периметрия + гониоскопия + OCT ДЗН (OS) — исключить глаукому", "критический", "2026-05-09", "разово", None, problem_ids.get("Незрелая катаракта OS + подозрение на глаукому")),
            ("YAG-лазерная дисцизия з/к OD", "высокий", "2026-06-15", "разово", None, problem_ids.get("Артифакия OD + ЗОСТ")),
            ("Липидный профиль + ЛП(a)", "высокий", "2026-05-30", "ежегодно", 1500, problem_ids.get("Атеросклероз")),
            ("HbA1c + глюкоза натощак", "высокий", "2026-05-30", "раз в 6 мес", 800, problem_ids.get("НАЖБП")),
            ("СМАД (24-ч мониторинг АД)", "средний", "2026-06-01", "ежегодно", 2500, problem_ids.get("Подозрение на гипертоническую болезнь")),
            ("DXA-денситометрия (поясничный + бедро)", "средний", "2026-07-01", "ежегодно", 3000, None),
            ("FibroScan/эластометрия печени", "средний", "2026-07-15", "ежегодно", 5000, problem_ids.get("НАЖБП")),
            ("Дневник самоконтроля АД (2 недели, 2×/день)", "средний", "2026-05-15", "ежедневно", None, problem_ids.get("Подозрение на гипертоническую болезнь")),
        ]
        for title, prio, deadline, freq, cost, prob_id in tasks:
            if title in existing_task_titles:
                continue
            c.post("/tasks", json={
                "patient_id": pid, "problem_id": prob_id, "title": title,
                "priority": prio, "deadline": deadline, "frequency": freq, "cost_rub": cost,
            })
            print(f"✓ задача: {title}")

        print("")
        print(f"🩺 Готово. Открой http://localhost:3000/patients/{pid}")


if __name__ == "__main__":
    try:
        main()
    except httpx.ConnectError as e:
        print(f"Backend недоступен: {e}", file=sys.stderr)
        print("Запусти 'make up' и подожди ~20 сек, затем повтори.", file=sys.stderr)
        sys.exit(1)
