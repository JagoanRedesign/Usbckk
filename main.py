from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pymongo import MongoClient
from pydantic import BaseModel
from typing import Optional, List
import os
from datetime import datetime

app = FastAPI(
    title="Quiz Bot API", 
    description="API untuk manajemen poin game kuis Telegram",
    version="1.0.0"
)

# ==================== KONFIGURASI ====================
# Ambil dari environment variable Koyeb
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("❌ MONGO_URI tidak ditemukan di environment variable!")

DB_NAME = os.getenv("DB_NAME", "quiz_bot")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "players")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise ValueError("❌ API_KEY tidak ditemukan di environment variable!")

PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")

print(f"🚀 Starting Quiz Bot API...")
print(f"📊 Database: {DB_NAME}")
print(f"📦 Collection: {COLLECTION_NAME}")
print(f"🔑 API Key: {'✅ Tersedia' if API_KEY else '❌ Tidak ada'}")

# ==================== KONEKSI MONGODB ====================
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Test koneksi
    client.admin.command('ping')
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    
    # Buat index untuk sorting poin
    collection.create_index("points", -1)
    collection.create_index("username")
    
    print("✅ Koneksi MongoDB berhasil!")
    print(f"📊 Total pemain saat ini: {collection.count_documents({})}")
    
except Exception as e:
    print(f"❌ Gagal koneksi MongoDB: {e}")
    # Jangan raise error di sini biar app tetap jalan, health check akan menunjukkan status
    client = None
    db = None
    collection = None

# ==================== FUNGSI VERIFIKASI ====================
def verify_api_key(api_key: str = Header(...)):
    """Verifikasi API Key dari header request"""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server configuration error: API_KEY not set")
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid API Key")
    return api_key

def get_collection():
    """Helper untuk mendapatkan collection dengan error handling"""
    if collection is None:
        raise HTTPException(status_code=503, detail="Database connection not available")
    return collection

# ==================== MODEL DATA ====================
class PointUpdate(BaseModel):
    user_id: int
    points: int  # bisa positif (tambah) atau negatif (kurang)
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

class LeaderboardResponse(BaseModel):
    leaderboard: List[PlayerResponse]
    total_players: int

class HealthResponse(BaseModel):
    status: str
    database: str
    total_players: int
    timestamp: str
    mongo_uri_configured: bool
    api_key_configured: bool

# ==================== ENDPOINTS ====================

@app.get("/")
async def root():
    """Root endpoint dengan informasi API"""
    return {
        "service": "Quiz Bot API",
        "version": "1.0.0",
        "status": "running",
        "database": "connected" if collection is not None else "disconnected",
        "endpoints": [
            {"method": "GET", "path": "/", "description": "Info API"},
            {"method": "GET", "path": "/health", "description": "Health check"},
            {"method": "GET", "path": "/points/{user_id}", "description": "GET poin pemain"},
            {"method": "POST", "path": "/points", "description": "POST update poin"},
            {"method": "GET", "path": "/leaderboard", "description": "GET peringkat"},
            {"method": "GET", "path": "/players", "description": "GET semua pemain"},
            {"method": "DELETE", "path": "/points/{user_id}", "description": "Reset poin pemain"}
        ]
    }

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Cek status API dan koneksi MongoDB
    Endpoint ini TIDAK memerlukan API Key untuk monitoring
    """
    db_status = "disconnected"
    total_players = 0
    
    try:
        if client:
            client.admin.command('ping')
            db_status = "connected"
            if collection:
                total_players = collection.count_documents({})
    except Exception as e:
        print(f"Health check error: {e}")
    
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
        "total_players": total_players,
        "timestamp": datetime.now().isoformat(),
        "mongo_uri_configured": bool(MONGO_URI),
        "api_key_configured": bool(API_KEY)
    }

@app.get("/points/{user_id}", response_model=PlayerResponse)
async def get_points(
    user_id: int, 
    api_key: str = Depends(verify_api_key)
):
    """
    Mendapatkan poin pemain berdasarkan user_id
    - Jika pemain tidak ada: dibuat dengan poin 0
    - Jika pemain ada: return poin saat ini
    """
    coll = get_collection()
    
    try:
        player = coll.find_one({"_id": user_id})
        
        if not player:
            # Pemain tidak ada - buat baru dengan poin 0
            new_player = {
                "_id": user_id,
                "points": 0,
                "first_name": None,
                "last_name": None,
                "username": None,
                "language_code": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "total_games": 0,
                "correct_answers": 0
            }
            coll.insert_one(new_player)
            print(f"✅ Pemain baru dibuat: {user_id}")
            
            return {
                "user_id": user_id,
                "points": 0,
                "first_name": None,
                "last_name": None,
                "username": None,
                "rank": None
            }
        
        # Hitung peringkat (opsional)
        rank = coll.count_documents({"points": {"$gt": player["points"]}}) + 1
        
        print(f"📊 Poin pemain {user_id}: {player['points']} (Rank: {rank})")
        return {
            "user_id": player["_id"],
            "points": player["points"],
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "username": player.get("username"),
            "rank": rank
        }
        
    except Exception as e:
        print(f"❌ Error get_points: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/points", response_model=PlayerResponse)
async def update_points(
    update: PointUpdate, 
    api_key: str = Depends(verify_api_key)
):
    """
    Update poin pemain
    - Jika pemain tidak ada: dibuat dengan poin yang diberikan
    - Jika pemain ada: poin ditambah/dikurang
    """
    coll = get_collection()
    
    try:
        # Data yang akan diupdate
        update_data = {"$inc": {"points": update.points}}
        
        # Data tambahan (jika ada)
        set_data = {
            "updated_at": datetime.now(),
            "$inc": {"total_games": 1}  # Tambah counter game
        }
        
        if update.points > 0:
            set_data["$inc"]["correct_answers"] = 1
        
        if update.first_name:
            set_data["first_name"] = update.first_name
        if update.last_name:
            set_data["last_name"] = update.last_name
        if update.username:
            set_data["username"] = update.username
        if update.language_code:
            set_data["language_code"] = update.language_code
        
        # Gabungkan update_data dengan set_data
        if "$set" in update_data:
            update_data["$set"].update(set_data)
        else:
            update_data["$set"] = set_data
        
        # Set created_at jika dokumen baru
        update_data["$setOnInsert"] = {
            "created_at": datetime.now(),
            "total_games": 0,
            "correct_answers": 0
        }
        
        # Update atau insert
        result = coll.update_one(
            {"_id": update.user_id},
            update_data,
            upsert=True
        )
        
        # Ambil data terbaru
        player = coll.find_one({"_id": update.user_id})
        
        # Hitung peringkat
        rank = coll.count_documents({"points": {"$gt": player["points"]}}) + 1
        
        action = "ditambahkan" if result.upserted_id else "diupdate"
        print(f"✅ Poin {action} untuk {update.user_id}: {update.points} (total: {player['points']})")
        
        return {
            "user_id": player["_id"],
            "points": player["points"],
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "username": player.get("username"),
            "rank": rank
        }
        
    except Exception as e:
        print(f"❌ Error update_points: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/leaderboard", response_model=List[PlayerResponse])
async def get_leaderboard(
    limit: int = Query(10, ge=1, le=50),
    api_key: str = Depends(verify_api_key)
):
    """
    Mendapatkan leaderboard
    - Default: 10 besar
    - Bisa diubah dengan parameter limit (max 50)
    """
    coll = get_collection()
    
    try:
        cursor = coll.find().sort("points", -1).limit(limit)
        
        leaderboard = []
        for rank, doc in enumerate(cursor, start=1):
            player = {
                "user_id": doc["_id"],
                "points": doc["points"],
                "first_name": doc.get("first_name"),
                "last_name": doc.get("last_name"),
                "username": doc.get("username"),
                "rank": rank
            }
            leaderboard.append(player)
        
        print(f"📊 Leaderboard diambil: {len(leaderboard)} pemain")
        return leaderboard
        
    except Exception as e:
        print(f"❌ Error leaderboard: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/players")
async def get_all_players(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Cari berdasarkan username atau first_name"),
    api_key: str = Depends(verify_api_key)
):
    """Mendapatkan semua pemain dengan pagination dan pencarian"""
    coll = get_collection()
    
    try:
        # Filter pencarian
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
            players.append({
                "user_id": doc["_id"],
                "points": doc["points"],
                "first_name": doc.get("first_name"),
                "last_name": doc.get("last_name"),
                "username": doc.get("username"),
                "total_games": doc.get("total_games", 0),
                "correct_answers": doc.get("correct_answers", 0)
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
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.delete("/points/{user_id}")
async def reset_points(
    user_id: int, 
    api_key: str = Depends(verify_api_key)
):
    """Reset poin pemain ke 0 (admin only)"""
    coll = get_collection()
    
    try:
        result = coll.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "points": 0, 
                    "updated_at": datetime.now()
                }
            }
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Player not found")
        
        print(f"🔄 Poin pemain {user_id} telah direset")
        return {
            "message": f"Poin pemain {user_id} telah direset ke 0",
            "success": True
        }
        
    except Exception as e:
        print(f"❌ Error reset_points: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/points/{user_id}/reset")
async def reset_points_post(
    user_id: int,
    api_key: str = Depends(verify_api_key)
):
    """Alternatif reset dengan method POST (untuk kompatibilitas)"""
    return await reset_points(user_id, api_key)

@app.get("/stats")
async def get_stats(api_key: str = Depends(verify_api_key)):
    """Mendapatkan statistik umum"""
    coll = get_collection()
    
    try:
        total_players = coll.count_documents({})
        total_points = sum(p.get("points", 0) for p in coll.find({}, {"points": 1}))
        
        # Top player
        top_player = coll.find_one(sort=[("points", -1)])
        
        return {
            "total_players": total_players,
            "total_points": total_points,
            "average_points": round(total_points / total_players, 2) if total_players > 0 else 0,
            "top_player": {
                "user_id": top_player["_id"] if top_player else None,
                "points": top_player["points"] if top_player else 0,
                "username": top_player.get("username") if top_player else None
            } if top_player else None,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"❌ Error stats: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ==================== EVENT HANDLER ====================
@app.on_event("startup")
async def startup_event():
    """Jalankan saat aplikasi start"""
    print("🚀 API starting up...")
    if collection is not None:
        print(f"📊 Total players in database: {collection.count_documents({})}")

@app.on_event("shutdown")
async def shutdown_event():
    """Jalankan saat aplikasi shutdown"""
    print("👋 API shutting down...")
    if client:
        client.close()

# ==================== RUNNER ====================
if __name__ == "__main__":
    import uvicorn
    print(f"🌐 Server running on http://{HOST}:{PORT}")
    print(f"📚 Documentation: http://{HOST}:{PORT}/docs")
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False  # Set True untuk development
    )
