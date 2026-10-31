#!/bin/sh
# Körs av nginx:alpine:s egen entrypoint-pipeline (/docker-entrypoint.d/*.sh, i
# filnamnsordning - detta är sist). Skriver ut rätt adress i loggarna efter start,
# så man slipper gissa/leta reda på porten själv.
echo ""
echo "=================================================================="
echo "EnergyWizard-gatewayn är uppe."
echo "Hemma hos din Home Assistant:  https://${DOMAIN}:${GATEWAY_PORT}/"
echo "EnergyWizard (dator/surfplatta): https://${DOMAIN}:${GATEWAY_PORT}/energywizard/"
echo "EnergyWizard (mobil):            https://${DOMAIN}:${GATEWAY_PORT}/energywizard/mobil/"
echo "=================================================================="
echo ""
