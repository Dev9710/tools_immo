from .views import bareme_info


def bareme(request):
    """Date et source du barème de taux, sur toutes les pages : un taux ne vaut
    que par sa date (consigne : toujours les taux les plus récents possible)."""
    return {'bareme': bareme_info()}
