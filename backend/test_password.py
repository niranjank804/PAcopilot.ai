from src.services.password_service import password_service

password = "Admin@123"

hashed = password_service.hash_password(password)

print(f"Original : {password}")
print(f"Hash     : {hashed}")
print(f"Verified : {password_service.verify_password(password, hashed)}")
