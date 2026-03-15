#!/usr/bin/env python3
"""
Script de diagnostic RSS Veille.
Exécuter depuis le container web :
  docker exec -it rss_web python scripts/diagnose.py

Ou via podman :
  podman exec -it rss_web python scripts/diagnose.py
"""
import sys
import os

sys.path.insert(0, "/app")
os.environ.setdefault("FLASK_ENV", "production")


def check_redis():
    print("\n=== Redis ===")
    try:
        import redis
        redis_url = os.environ.get("REDIS_URL", "redis://:redispass@redis:6379/0")
        r = redis.from_url(redis_url, socket_connect_timeout=5)
        pong = r.ping()
        print(f"  ✅ Redis OK (ping={pong})")
        print(f"  URL : {redis_url}")
        return True
    except Exception as e:
        print(f"  ❌ Redis ERREUR : {e}")
        return False


def check_celery_workers():
    print("\n=== Celery Workers ===")
    try:
        from services.scheduler_tasks import celery_app
        inspector = celery_app.control.inspect(timeout=5.0)
        active = inspector.active()
        if active:
            print(f"  ✅ {len(active)} worker(s) actif(s) :")
            for worker, tasks in active.items():
                print(f"     - {worker} : {len(tasks)} tâche(s) en cours")
        else:
            print("  ❌ Aucun worker Celery ne répond !")
            print("  → Vérifiez : podman-compose logs rss_celery_worker")
        return bool(active)
    except Exception as e:
        print(f"  ❌ Erreur inspection Celery : {e}")
        return False


def check_celery_beat():
    print("\n=== Celery Beat Schedule ===")
    try:
        from services.scheduler_tasks import celery_app
        schedule = celery_app.conf.beat_schedule
        print(f"  ✅ {len(schedule)} tâches planifiées :")
        for name, task in schedule.items():
            print(f"     - {name} : {task['schedule']}")
        return True
    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        return False


def check_database():
    print("\n=== Base de données ===")
    try:
        from main import create_app, db
        app = create_app()
        with app.app_context():
            from models.user import User
            from models.feed import Feed
            from models.article import Article
            from models.synthesis import Synthesis

            users = User.query.count()
            feeds = Feed.query.count()
            active_feeds = Feed.query.filter_by(active=True).count()
            articles = Article.query.count()
            syntheses = Synthesis.query.count()

            print(f"  ✅ Connexion OK")
            print(f"     Utilisateurs : {users}")
            print(f"     Flux RSS : {feeds} total, {active_feeds} actifs")
            print(f"     Articles : {articles}")
            print(f"     Synthèses : {syntheses}")

            # Vérifier les flux jamais collectés
            never_fetched = Feed.query.filter_by(active=True, last_fetched=None).count()
            if never_fetched > 0:
                print(f"  ⚠️  {never_fetched} flux actif(s) jamais collecté(s) !")
                print("     → Lancez la collecte depuis /admin/tasks ou via la tâche Celery")

        return True
    except Exception as e:
        print(f"  ❌ Erreur DB : {e}")
        return False


def run_test_fetch():
    print("\n=== Test collecte RSS (1 flux) ===")
    try:
        from main import create_app, db
        app = create_app()
        with app.app_context():
            from models.feed import Feed
            from services.rss_fetcher import fetch_feed_articles

            feed = Feed.query.filter_by(active=True).first()
            if not feed:
                print("  ⚠️  Aucun flux actif trouvé")
                return False

            print(f"  Test sur : {feed.url}")
            articles, error = fetch_feed_articles(feed.url, None)
            if error:
                print(f"  ❌ Erreur : {error}")
                return False
            print(f"  ✅ {len(articles)} articles récupérés")
            if articles:
                print(f"     Premier article : {articles[0]['title'][:80]}")
        return True
    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        return False


def trigger_fetch_task():
    print("\n=== Déclenchement tâche fetch_all_feeds ===")
    try:
        from services.scheduler_tasks import fetch_all_feeds
        task = fetch_all_feeds.delay()
        print(f"  ✅ Tâche envoyée à Celery (task_id={task.id})")
        print("  → Attendez quelques secondes puis vérifiez :")
        print("    podman-compose logs -f rss_celery_worker")
        return True
    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("  RSS Veille — Diagnostic")
    print("=" * 50)

    redis_ok = check_redis()
    db_ok = check_database()
    beat_ok = check_celery_beat()
    workers_ok = check_celery_workers()

    print("\n=== Test RSS ===")
    fetch_ok = run_test_fetch()

    print("\n=== Résumé ===")
    checks = [
        ("Redis", redis_ok),
        ("Base de données", db_ok),
        ("Beat schedule", beat_ok),
        ("Workers Celery", workers_ok),
        ("Collecte RSS", fetch_ok),
    ]
    all_ok = True
    for name, ok in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n✅ Tout est opérationnel !")
        print("Déclenchement d'une collecte test...")
        trigger_fetch_task()
    else:
        print("\n⚠️  Des problèmes ont été détectés. Consultez les détails ci-dessus.")
        if not workers_ok:
            print("\n→ SOLUTION PRINCIPALE : Le worker Celery ne répond pas.")
            print("  Vérifiez les logs : podman-compose logs rss_celery_worker")
            print("  Redémarrez si nécessaire : podman-compose restart rss_celery_worker rss_celery_beat")

    print()
