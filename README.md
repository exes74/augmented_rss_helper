# 📰 RSS Veille — Application de veille intelligente

Application web complète de veille RSS avec synthèses automatisées par IA, optimisée pour la création de contenu LinkedIn.

## 🌟 Fonctionnalités

- **Gestion des flux RSS** : Ajout, validation, catégorisation et suivi de l'état des flux.
- **Collecte automatisée** : Récupération quotidienne des articles via Celery Beat.
- **Synthèses IA** :
  - *Quotidiennes* : Résumé des articles du jour par catégorie (tendances clés, sources).
  - *Hebdomadaires* : Synthèse de la semaine avec **draft de post LinkedIn** prêt à publier.
- **Envoi d'emails** : Réception des synthèses directement dans votre boîte mail (SMTP ou SendGrid).
- **Multi-utilisateurs** : Système d'invitation, rôles (Admin/User), partage de synthèses à des emails tiers.
- **Interface minimaliste** : Design épuré avec Tailwind CSS, rapide et responsive.

## 🛠️ Stack Technique

- **Backend** : Python 3.11, Flask, SQLAlchemy
- **Base de données** : PostgreSQL 15
- **Cache & Queue** : Redis 7
- **Tâches asynchrones** : Celery & Celery Beat
- **IA** : OpenAI API (GPT-4o-mini) ou Ollama (LLM local)
- **Serveur Web** : Nginx (Reverse Proxy)
- **Déploiement** : Docker & Docker Compose

---

## 🚀 Guide de déploiement sur VPS Debian

Ce guide explique comment déployer l'application sur un VPS sous Debian/Ubuntu.

### 1. Prérequis système

Connectez-vous à votre VPS en SSH et mettez à jour le système :

```bash
sudo apt update && sudo apt upgrade -y
```

Installez Docker et Docker Compose :

```bash
# Installation de Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Installation de Docker Compose
sudo apt install docker-compose-plugin -y

# Vérification
docker --version
docker compose version
```

### 2. Installation de l'application

Clonez le dépôt ou transférez les fichiers sur votre serveur :

```bash
mkdir -p /opt/rss-veille
cd /opt/rss-veille
# Copiez les fichiers du projet ici
```

### 3. Configuration

Créez le fichier d'environnement à partir de l'exemple :

```bash
cp .env.example .env
nano .env
```

**Variables obligatoires à modifier :**
- `SECRET_KEY` : Générez une chaîne aléatoire longue (ex: `openssl rand -hex 32`)
- `APP_URL` : L'URL de votre site (ex: `https://veille.mondomaine.com`)
- `POSTGRES_PASSWORD` : Un mot de passe fort pour la base de données
- `REDIS_PASSWORD` : Un mot de passe fort pour Redis
- `OPENAI_API_KEY` : Votre clé API OpenAI (si vous utilisez OpenAI)
- `SMTP_*` : Vos identifiants SMTP pour l'envoi d'emails

### 4. Configuration SSL (HTTPS)

Par défaut, Nginx est configuré pour écouter sur les ports 80 et 443.
Vous devez générer des certificats SSL.

**Option A : Certificats Let's Encrypt (Recommandé pour la production)**

```bash
sudo apt install certbot -y
sudo certbot certonly --standalone -d votre-domaine.com
```
Copiez ensuite les certificats dans le dossier attendu par Nginx :
```bash
mkdir -p nginx_ssl
sudo cp /etc/letsencrypt/live/votre-domaine.com/fullchain.pem nginx_ssl/cert.pem
sudo cp /etc/letsencrypt/live/votre-domaine.com/privkey.pem nginx_ssl/key.pem
```

**Option B : Certificats auto-signés (Pour le développement/test)**

```bash
mkdir -p nginx_ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx_ssl/key.pem -out nginx_ssl/cert.pem \
  -subj "/C=FR/ST=Paris/L=Paris/O=Dev/CN=localhost"
```

### 5. Lancement de l'application

Démarrez tous les conteneurs en arrière-plan :

```bash
docker compose up -d --build
```

Vérifiez que tous les conteneurs tournent correctement :

```bash
docker compose ps
docker compose logs -f web
```

### 6. Création du compte Administrateur

Une fois l'application lancée, vous devez créer le premier compte administrateur.
Exécutez cette commande dans le conteneur web :

```bash
docker compose exec web flask shell
```

Puis dans le shell Python interactif :

```python
from main import db
from models.user import User

admin = User(email="admin@votre-domaine.com", role="admin", is_verified=True)
admin.set_password("votre-mot-de-passe-securise")
db.session.add(admin)
db.session.commit()
exit()
```

Vous pouvez maintenant vous connecter à l'interface web avec ces identifiants ! 🎉

---

## 🤖 Utilisation d'Ollama (LLM Local)

Si vous préférez utiliser un modèle local (ex: Llama 3) pour des raisons de confidentialité ou de coût :

1. Décommentez la section `ollama` dans le fichier `docker-compose.yml`
2. Dans votre fichier `.env`, modifiez :
   ```env
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://ollama:11434
   OLLAMA_MODEL=llama3.1
   ```
3. Redémarrez les conteneurs : `docker compose up -d`
4. Téléchargez le modèle dans le conteneur Ollama :
   ```bash
   docker compose exec ollama ollama run llama3.1
   ```
*(Note : L'utilisation d'Ollama nécessite un VPS avec suffisamment de RAM, idéalement 16Go+, ou un GPU).*

---

## 📝 Commandes utiles

**Voir les logs en temps réel :**
```bash
docker compose logs -f
```

**Redémarrer un service spécifique (ex: celery_worker) :**
```bash
docker compose restart celery_worker
```

**Mettre à jour l'application :**
```bash
git pull
docker compose up -d --build
```

**Sauvegarder la base de données :**
```bash
docker compose exec postgres pg_dump -U rssuser rssveille > backup.sql
```
