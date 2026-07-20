from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..services.kra_service import KraService
from .auth_router import get_current_user
from ..models import User

class PinCheckRequest(BaseModel):
    pin: str

class NilFilingRequest(BaseModel):
    pin: str
    obligation_code: str
    month: str
    year: str

class PinGenerationRequest(BaseModel):
    id_number: str
    dob: str # DD/MM/YYYY
    mobile: str
    id_number: str
    dob: str # DD/MM/YYYY
    mobile: str
    email: str
    taxpayer_type: str = "KE"
    is_pin_with_no_oblig: str = "Yes"

router = APIRouter(prefix="/kra", tags=["KRA GavaConnect"])

@router.post("/check-pin")
async def check_pin(
    request: PinCheckRequest,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Check KRA PIN status."""
    kra_service = KraService()
    result = await kra_service.check_pin(request.pin)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=result.get("status_code", 400),
            detail=result.get("error")
        )
        
    return result

@router.post("/check-id")
async def check_id(
    request: Dict[str, str], # {"id_number": "..."}
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Check KRA PIN by ID Number."""
    id_number = request.get("id_number")
    taxpayer_type = request.get("taxpayer_type", "KE")
    
    if not id_number:
        raise HTTPException(status_code=400, detail="ID Number is required")
        
    kra_service = KraService()
    result = await kra_service.get_pin_by_id(id_number, taxpayer_type)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
        
    return result

@router.post("/file-nil-return")
async def file_nil_return(
    request: NilFilingRequest,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """File a NIL return."""
    kra_service = KraService()
    result = await kra_service.file_nil_return(
        pin=request.pin,
        obligation_code=request.obligation_code,
        month=request.month,
        year=request.year
    )
    
    if not result.get("success"):
         raise HTTPException(status_code=400, detail=result.get("error"))
         
    return result

@router.post("/generate-pin")
async def generate_pin(
    request: PinGenerationRequest,
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Generate a new KRA PIN."""
    kra_service = KraService()
    result = await kra_service.generate_pin(
        id_number=request.id_number,
        dob=request.dob,
        mobile=request.mobile,
        email=request.email,
        taxpayer_type=request.taxpayer_type,
        is_pin_with_no_oblig=request.is_pin_with_no_oblig
    )
    
    if not result.get("success"):
         raise HTTPException(
            status_code=result.get("status_code", 400),
            detail=result.get("error")
        )
         
    return result
