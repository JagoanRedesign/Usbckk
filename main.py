from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pymongo import MongoClient, UpdateOne
from pymongo.errors import ConnectionFailure, BulkWriteError
from pydantic import BaseModel, validator
from typing import Optional, List, Dict
from datetime import datetime
from contextlib import asynccontextmanager
import os
import sys
import traceback

# ==================== KONFIGURASI LANGSUNG ====================
MONGO_URI = "mongodb+srv://galeh:galeh@cluster0.cq2tj1u.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "quiz_bot"
API_KEY = "kunci975635885rii7"
PORT = 8000
HOST = "0.0.0.0"

PORT = int(os.environ.get("PORT", PORT))

# ==================== VARIABEL GLOBAL ====================
client = None
db = None
collections = {}  # Dictionary untuk menyimpan collection per game

print(f"🐍 Python version: {sys.version}")
print(f"🔌 MongoDB URI: {MONGO_URI[:50]}...")

# ==================== LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db, collections
    print(f"🚀 Starting Multi-Game Quiz Bot API...")
    print(f"📊 Database: {DB_NAME}")
    print(f"🔑 API Key: {'✅ Tersedia' if API_KEY else '❌ Tidak ada'}")

    try:
        print("🔄 Menghubungkan ke MongoDB...")
        client = MongoClient(
            MONGO_URI,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=30000
        )
        client.admin.command('ping')
        print("✅ Ping MongoDB berhasil!")

        db = client[DB_NAME]
        
        # Daftar game yang didukung
        GAMES = ["kuis", "susunkata", "tebakkata", "tebakgambar", "matematika"]
        
        # Inisialisasi collection untuk setiap game
        for game in GAMES:
            collection_name = f"{game}_players"
            collections[game] = db[collection_name]
            
            # Buat index
            try:
                collections[game].create_index("points", -1)
                collections[game].create_index("username")
                print(f"✅ Index untuk {game} berhasil dibuat")
            except Exception as idx_err:
                print(f"⚠️ Gagal membuat index untuk {game}: {idx_err}")
            
            # Hitung total pemain per game
            total = collections[game].count_documents({})
            print(f"📊 Total pemain {game}: {total}")

        print("✅ Koneksi MongoDB BERHASIL dengan multi-game support!")
    except Exception as e:
        print(f"❌ Gagal koneksi MongoDB: {type(e).__name__}: {e}")
        traceback.print_exc()
        client = None
        db = None
        collections = {}

    yield

    print("👋 API shutting down...")
    if client:
        client.close()
        print("✅ Koneksi MongoDB ditutup")

# ==================== INISIALISASI APP ====================
app = FastAPI(
    title="Multi-Game Quiz Bot API",
    description="API untuk manajemen poin berbagai game kuis Telegram",
    version="2.1.0",
    lifespan=lifespan
)

# ==================== FUNGSI VERIFIKASI ====================
def verify_api_key(api_key: str = Header(...)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server configuration error: API_KEY not set")
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")
    return api_key

def get_collection(game_name: str):
    """Mendapatkan collection berdasarkan nama game"""
    if game_name not in collections:
        raise HTTPException(status_code=404, detail=f"Game '{game_name}' tidak ditemukan")
    if collections[game_name] is None:
        raise HTTPException(
            status_code=503, 
            detail="Database connection not available. Please check /health endpoint."
        )
    return collections[game_name]

# ==================== MODEL DATA ====================
class PointUpdate(BaseModel):
    user_id: int
    points: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None

class PlayerResponse(BaseModel):
    user_id: int
    points: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    rank: Optional[int] = None
    total_games: Optional[int] = None
    correct_answers: Optional[int] = None

class HealthResponse(BaseModel):
    status: str
    database: str
    games: Dict[str, int]
    timestamp: str
    mongo_uri_configured: bool
    api_key_configured: bool
    error_detail: Optional[str] = None

# ==================== IMPROVED BULK IMPORT MODEL ====================
class BulkPlayerData(BaseModel):
    user_id: int
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    username: Optional[str] = ""
    points: Optional[int] = 0
    language_code: Optional[str] = "id"
    
    @validator('user_id')
    def validate_user_id(cls, v):
        if v <= 0:
            raise ValueError('user_id must be positive')
        if v > 9999999999:  # Telegram max user_id
            raise ValueError('user_id too large')
        return v
    
    @validator('points')
    def validate_points(cls, v):
        if v is None:
            return 0
        if v < -10000000 or v > 10000000:
            raise ValueError(f'points out of reasonable range (max 10 million): {v}')
        return v
    
    @validator('first_name', 'last_name', 'username')
    def clean_strings(cls, v):
        if v is None:
            return ""
        return str(v).strip()[:100]

class BulkImportResponse(BaseModel):
    success: bool
    message: str
    stats: Dict
    errors: List[str]
    warnings: List[str]

# ==================== ENDPOINTS UTAMA ====================
@app.get("/")
async def root():
    games_status = {}
    for game, coll in collections.items():
        try:
            total = coll.count_documents({})
            games_status[game] = total
        except:
            games_status[game] = -1
    
    return {
        "service": "Multi-Game Quiz Bot API",
        "version": "2.1.0",
        "status": "running",
        "database": "connected" if client is not None else "disconnected",
        "games": list(collections.keys()),
        "games_stats": games_status,
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Info API"},
            {"method": "GET", "path": "/health", "description": "Health check (public)"},
            {"method": "GET", "path": "/{game}/points/{user_id}", "description": "GET poin pemain"},
            {"method": "POST", "path": "/{game}/points", "description": "POST update poin"},
            {"method": "GET", "path": "/{game}/leaderboard", "description": "GET peringkat (sederhana)"},
            {"method": "GET", "path": "/{game}/players", "description": "GET semua pemain (sederhana)"},
            {"method": "DELETE", "path": "/{game}/points/{user_id}", "description": "Reset poin"},
            {"method": "GET", "path": "/{game}/stats", "description": "GET statistik"},
            {"method": "GET", "path": "/{game}/top/{count}", "description": "GET N pemain teratas"},
            {"method": "POST", "path": "/bulk-import/{game}", "description": "Bulk import players"},
            {"method": "GET", "path": "/bulk-import/{game}/status", "description": "Check import status"},
            {"method": "GET", "path": "/debug/connection", "description": "Debug koneksi"}
        ]
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    db_status = "disconnected"
    games_stats = {}
    error_detail = None

    try:
        if client:
            try:
                client.admin.command('ping')
                db_status = "connected"
            except Exception as e:
                error_detail = str(e)
                db_status = "error"

            if db_status == "connected":
                for game, coll in collections.items():
                    try:
                        games_stats[game] = coll.count_documents({})
                    except Exception:
                        games_stats[game] = -1
    except Exception as e:
        print(f"Health check error: {e}")
        error_detail = str(e)

    overall_status = "healthy" if db_status == "connected" else "unhealthy"
    return {
        "status": overall_status,
        "database": db_status,
        "games": games_stats,
        "timestamp": datetime.now().isoformat(),
        "mongo_uri_configured": bool(MONGO_URI),
        "api_key_configured": bool(API_KEY),
        "error_detail": error_detail
    }

# ==================== ENDPOINTS GAME (SEDERHANA) ====================
@app.get("/{game}/points/{user_id}")
async def get_points(
    game: str,
    user_id: int, 
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        player = coll.find_one({"_id": user_id})
        if not player:
            return {
                "user_id": user_id,
                "points": 0,
                "nama": None
            }
        
        # Buat nama
        nama = player.get("first_name") or ""
        if player.get("last_name"):
            nama += " " + player.get("last_name")
        nama = nama.strip()
        if not nama and player.get("username"):
            nama = "@" + player.get("username")
        if not nama:
            nama = f"User{user_id}"
        
        return {
            "user_id": user_id,
            "points": player["points"],
            "nama": nama
        }
    except Exception as e:
        print(f"❌ Error get_points: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/{game}/points", response_model=PlayerResponse)
async def update_points(
    game: str,
    update: PointUpdate, 
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        update_ops = {}
        inc_fields = {}
        if update.points != 0:
            inc_fields["points"] = update.points
            inc_fields["total_games"] = 1
            if update.points > 0:
                inc_fields["correct_answers"] = 1
        if inc_fields:
            update_ops["$inc"] = inc_fields

        set_fields = {"updated_at": datetime.now()}
        if update.first_name:
            set_fields["first_name"] = update.first_name
        if update.last_name:
            set_fields["last_name"] = update.last_name
        if update.username:
            set_fields["username"] = update.username
        if set_fields:
            update_ops["$set"] = set_fields

        update_ops["$setOnInsert"] = {"created_at": datetime.now()}

        result = coll.update_one(
            {"_id": update.user_id},
            update_ops,
            upsert=True
        )

        player = coll.find_one({"_id": update.user_id})
        rank = coll.count_documents({"points": {"$gt": player["points"]}}) + 1

        action = "ditambahkan" if result.upserted_id else "diupdate"
        print(f"✅ Poin {action} di game {game} untuk {update.user_id}: {update.points}")
        return {
            "user_id": player["_id"],
            "points": player["points"],
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "username": player.get("username"),
            "rank": rank,
            "total_games": player.get("total_games", 0),
            "correct_answers": player.get("correct_answers", 0)
        }
    except Exception as e:
        print(f"❌ Error update_points: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{game}/leaderboard")
async def get_leaderboard(
    game: str,
    limit: int = Query(10, ge=1, le=50),
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        cursor = coll.find().sort("points", -1).limit(limit)
        leaderboard = []
        for doc in cursor:
            # Buat nama
            nama = doc.get("first_name") or ""
            if doc.get("last_name"):
                nama += " " + doc.get("last_name")
            nama = nama.strip()
            if not nama and doc.get("username"):
                nama = "@" + doc.get("username")
            if not nama:
                nama = f"User{doc['_id']}"
            
            leaderboard.append({
                "user_id": doc["_id"],
                "points": doc["points"],
                "nama": nama
            })
        print(f"📊 Leaderboard {game} diambil: {len(leaderboard)} pemain")
        return leaderboard
    except Exception as e:
        print(f"❌ Error leaderboard: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{game}/players")
async def get_all_players(
    game: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        filter_query = {}
        if search:
            filter_query = {
                "$or": [
                    {"username": {"$regex": search, "$options": "i"}},
                    {"first_name": {"$regex": search, "$options": "i"}}
                ]
            }
        total = coll.count_documents(filter_query)
        cursor = coll.find(filter_query).sort("points", -1).skip(skip).limit(limit)
        players = []
        for doc in cursor:
            # Buat nama
            nama = doc.get("first_name") or ""
            if doc.get("last_name"):
                nama += " " + doc.get("last_name")
            nama = nama.strip()
            if not nama and doc.get("username"):
                nama = "@" + doc.get("username")
            if not nama:
                nama = f"User{doc['_id']}"
            
            players.append({
                "user_id": doc["_id"],
                "points": doc["points"],
                "nama": nama
            })
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "search": search,
            "players": players
        }
    except Exception as e:
        print(f"❌ Error get_all_players: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/{game}/points/{user_id}")
async def reset_points(
    game: str,
    user_id: int, 
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        player = coll.find_one({"_id": user_id})
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")
        coll.update_one(
            {"_id": user_id},
            {"$set": {"points": 0, "updated_at": datetime.now()}}
        )
        print(f"🔄 Poin pemain {user_id} di game {game} telah direset")
        return {"message": f"Poin pemain {user_id} telah direset", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error reset_points: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{game}/stats")
async def get_game_stats(
    game: str,
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        total_players = coll.count_documents({})
        pipeline = [
            {"$group": {
                "_id": None,
                "total_points": {"$sum": "$points"},
                "avg_points": {"$avg": "$points"},
                "max_points": {"$max": "$points"}
            }}
        ]
        stats = list(coll.aggregate(pipeline))
        top_player = coll.find_one(sort=[("points", -1)])
        
        return {
            "game": game,
            "total_players": total_players,
            "total_points": stats[0]["total_points"] if stats else 0,
            "average_points": round(stats[0]["avg_points"], 2) if stats else 0,
            "max_points": stats[0]["max_points"] if stats else 0,
            "top_player": {
                "user_id": top_player["_id"] if top_player else None,
                "points": top_player["points"] if top_player else 0
            } if top_player else None,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"❌ Error stats: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{game}/top/{count}")
async def get_top_players(
    game: str,
    count: int,
    api_key: str = Depends(verify_api_key)
):
    coll = get_collection(game)
    try:
        if count < 1 or count > 100:
            count = 10
        cursor = coll.find().sort("points", -1).limit(count)
        top_players = []
        for doc in cursor:
            nama = doc.get("first_name") or doc.get("username") or f"User{doc['_id']}"
            top_players.append({
                "rank": len(top_players) + 1,
                "user_id": doc["_id"],
                "points": doc["points"],
                "nama": nama
            })
        return {"game": game, "count": len(top_players), "top_players": top_players}
    except Exception as e:
        print(f"❌ Error get_top_players: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ==================== BULK IMPORT ENDPOINT ====================
@app.post("/bulk-import/{game}", response_model=BulkImportResponse)
async def bulk_import(
    game: str,
    players: List[dict],
    api_key: str = Depends(verify_api_key),
    mode: str = Query("add", regex="^(add|replace)$"),
    validate_only: bool = Query(False)
):
    try:
        if not players:
            raise HTTPException(status_code=400, detail="No players data provided")
        
        if len(players) > 10000:
            raise HTTPException(status_code=400, detail=f"Maximum 10000 players per import")
        
        coll = get_collection(game)
        valid_players = []
        errors = []
        
        for idx, p in enumerate(players):
            try:
                player = BulkPlayerData(**p)
                valid_players.append(player)
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)}")
        
        if validate_only:
            return {
                "success": len(errors) == 0,
                "message": f"Validation: {len(valid_players)} valid, {len(errors)} errors",
                "stats": {"valid": len(valid_players), "errors": len(errors)},
                "errors": errors[:50],
                "warnings": []
            }
        
        # Deduplikasi
        seen_ids = {}
        deduplicated = []
        for player in valid_players:
            if player.user_id not in seen_ids:
                seen_ids[player.user_id] = True
                deduplicated.append(player)
        
        operations = []
        now = datetime.now()
        
        for player in deduplicated:
            first_name = player.first_name.strip() if player.first_name else ""
            username = player.username.strip() if player.username else ""
            
            if not first_name and not username:
                first_name = f"Player_{player.user_id}"
            
            if mode == "replace":
                operations.append(
                    UpdateOne(
                        {"_id": player.user_id},
                        {"$set": {"points": player.points, "first_name": first_name,
                                 "username": username, "updated_at": now,
                                 "imported_from_sheet": True},
                         "$setOnInsert": {"created_at": now}},
                        upsert=True
                    )
                )
            else:
                operations.append(
                    UpdateOne(
                        {"_id": player.user_id},
                        {"$set": {"first_name": first_name, "username": username,
                                 "updated_at": now, "imported_from_sheet": True},
                         "$inc": {"points": player.points},
                         "$setOnInsert": {"created_at": now}},
                        upsert=True
                    )
                )
        
        total_modified = 0
        total_upserted = 0
        bulk_errors = []
        
        if operations:
            try:
                result = coll.bulk_write(operations, ordered=False)
                total_modified = result.modified_count
                total_upserted = result.upserted_count
            except BulkWriteError as bwe:
                total_modified = bwe.details.get('nModified', 0)
                total_upserted = bwe.details.get('nUpserted', 0)
                write_errors = bwe.details.get('writeErrors', [])
                for err in write_errors[:20]:
                    bulk_errors.append(f"Index {err['index']}: {err.get('errmsg', 'Unknown')}")
        
        final_count = coll.count_documents({})
        
        return {
            "success": len(bulk_errors) == 0,
            "message": f"Bulk import completed for '{game}'",
            "stats": {
                "total_received": len(players),
                "valid": len(valid_players),
                "unique": len(deduplicated),
                "modified": total_modified,
                "upserted": total_upserted,
                "total_in_db": final_count
            },
            "errors": (errors + bulk_errors)[:50],
            "warnings": []
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Bulk import error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Bulk import failed: {str(e)}")

# ==================== BULK STATUS ENDPOINT ====================
@app.get("/bulk-import/{game}/status")
async def check_bulk_status(
    game: str,
    api_key: str = Depends(verify_api_key)
):
    try:
        coll = get_collection(game)
        total = coll.count_documents({})
        top5 = list(coll.find().sort("points", -1).limit(5))
        
        return {
            "game": game,
            "total_players": total,
            "top_5": [
                {
                    "user_id": p["_id"],
                    "name": p.get("first_name") or p.get("username") or f"Player {p['_id']}",
                    "points": p["points"]
                } for p in top5
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== DEBUG ENDPOINT ====================
@app.get("/debug/connection")
async def debug_connection(api_key: str = Depends(verify_api_key)):
    return {
        "python_version": sys.version,
        "client_exists": client is not None,
        "collections": list(collections.keys()) if collections else []
    }

# ==================== RUNNER ====================
if __name__ == "__main__":
    import uvicorn
    print(f"🌐 Server akan berjalan di http://{HOST}:{PORT}")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
