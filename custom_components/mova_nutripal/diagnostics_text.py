"""Warning bits from feeder plugin; unrecognized bits stay explicit."""
WARN = [
('Croquettes bloquées','Kibble jam'),('Manque de croquettes','Low kibble'),
('Compléments bloqués','Supplement jam'),('Anomalie de pesée','Weighing fault'),
('Aucune croquette détectée','No kibble detected'),('Accumulation dans le bol','Food accumulation'),
('Manque de compléments','Low supplements'),('Piles faibles','Low batteries'),
('Réservoir de compléments absent','Supplement container missing'),('Couvercle de compléments absent','Supplement lid missing'),
('Bol mal installé','Bowl not installed correctly'),('Dessiccant à remplacer','Replace desiccant')]
# Fault enum names in the bundle are inconsistent across language resources.
# Do not invent an exact meaning for a nonzero fault bit.
def mask_messages(key, value, language):
    if type(value) is not int or value < 0:
        return None
    fr = language.startswith('fr')
    if value == 0:
        return ['Aucune anomalie' if fr else 'No anomaly']
    result = []
    known = 0
    if key == 'warning_mask':
        for i, texts in enumerate(WARN):
            bit = 1 << i
            if value & bit:
                result.append(texts[0 if fr else 1]); known |= bit
    if value & ~known:
        result.append(('Code non identifié : ' if fr else 'Unidentified code: ') + str(value & ~known))
    return result
