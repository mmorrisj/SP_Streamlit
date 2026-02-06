# ============================================
# Stop All Services (PowerShell)
# Standalone Docker (no Docker Compose)
# ============================================

Write-Host ""
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host "Stopping All Services" -ForegroundColor Yellow
Write-Host "==============================================" -ForegroundColor Yellow
Write-Host ""

Write-Host "🛑 Stopping containers..." -ForegroundColor Cyan

try { docker stop softpower_pipeline 2>$null; Write-Host "✅ Pipeline stopped" -ForegroundColor Green } catch { Write-Host "⚠️  Pipeline not running" -ForegroundColor Yellow }
try { docker stop softpower_dashboard 2>$null; Write-Host "✅ Streamlit stopped" -ForegroundColor Green } catch { Write-Host "⚠️  Streamlit not running" -ForegroundColor Yellow }
try { docker stop softpower_api 2>$null; Write-Host "✅ Web app stopped" -ForegroundColor Green } catch { Write-Host "⚠️  Web app not running" -ForegroundColor Yellow }
try { docker stop softpower_redis 2>$null; Write-Host "✅ Redis stopped" -ForegroundColor Green } catch { Write-Host "⚠️  Redis not running" -ForegroundColor Yellow }
try { docker stop softpower_db 2>$null; Write-Host "✅ PostgreSQL stopped" -ForegroundColor Green } catch { Write-Host "⚠️  PostgreSQL not running" -ForegroundColor Yellow }

Write-Host ""
Write-Host "🗑️  Removing containers..." -ForegroundColor Cyan

try { docker rm softpower_pipeline 2>$null; Write-Host "✅ Pipeline removed" -ForegroundColor Green } catch { }
try { docker rm softpower_dashboard 2>$null; Write-Host "✅ Streamlit removed" -ForegroundColor Green } catch { }
try { docker rm softpower_api 2>$null; Write-Host "✅ Web app removed" -ForegroundColor Green } catch { }
try { docker rm softpower_redis 2>$null; Write-Host "✅ Redis removed" -ForegroundColor Green } catch { }
try { docker rm softpower_db 2>$null; Write-Host "✅ PostgreSQL removed" -ForegroundColor Green } catch { }

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "✅ All Services Stopped" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Data preserved in volumes:"
Write-Host "  • postgres_data"
Write-Host "  • redis_data"
Write-Host ""
Write-Host "To remove data (WARNING: deletes all data):" -ForegroundColor Yellow
Write-Host "  docker volume rm postgres_data redis_data"
Write-Host ""
Write-Host "To restart services:"
Write-Host "  .\docker\run-all.ps1"
Write-Host ""
