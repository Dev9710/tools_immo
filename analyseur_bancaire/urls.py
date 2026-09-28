from django.urls import path
from . import views

urlpatterns = [
    path('', views.accueil, name='accueil'),
    path('depenses-mensuelles/', views.depenses_mensuelles,
         name='depenses_mensuelles'),
    path('depenses-mensuelles/export-excel/', views.export_depenses_excel,
         name='export_depenses_excel'),
    path('upload/', views.upload_releve, name='upload_releve'),
    path('charges-fixes/', views.charges_fixes, name='charges_fixes'),
    path('simulateur-pret/', views.simulateur_pret, name='simulateur_pret'),
    path('dashboard/', views.dashboard_dossier, name='dashboard'),
    path('export-dossier-pdf/', views.export_dossier_pdf,
         name='export_dossier_pdf'),
    path('biens-financables/', views.biens_financables, name='biens_financables'),
]
