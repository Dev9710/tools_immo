from django.urls import path
from . import views

urlpatterns = [
    path('', views.accueil, name='accueil'),
    path('upload/', views.upload_releve, name='upload_releve'),
    path('charges-fixes/', views.charges_fixes, name='charges_fixes'),
    path('simulateur-pret/', views.simulateur_pret, name='simulateur_pret'),
    path('dashboard/', views.dashboard_dossier, name='dashboard'),
    path('export-dossier-pdf/', views.export_dossier_pdf,
         name='export_dossier_pdf'),
]
