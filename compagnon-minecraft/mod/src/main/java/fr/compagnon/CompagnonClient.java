package fr.compagnon;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.network.chat.Component;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.effect.MobEffectInstance;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.monster.Enemy;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;

/**
 * Capteur du compagnon IA : deux fois par seconde, écrit l'état du joueur et de ce qui l'entoure dans
 * {@code <dossier du jeu>/compagnon/etat.json}. Lecture seule : le mod ne modifie rien dans la partie.
 */
public class CompagnonClient implements ClientModInitializer {
	private static final int PERIODE_TICKS = 10; // 20 ticks = 1 seconde
	private static final double RAYON_MONSTRES = 24.0;
	private static final int EVENEMENTS_MAX = 20;
	private static final Pattern IDENTIFIANT = Pattern.compile("([a-z0-9_.-]+):([a-z0-9_./-]+)");

	private final Gson gson = new Gson();
	private final ExecutorService ecrivain = Executors.newSingleThreadExecutor(r -> {
		Thread t = new Thread(r, "compagnon-ecriture");
		t.setDaemon(true);
		return t;
	});
	private final Deque<JsonObject> evenements = new ArrayDeque<>();
	private Path fichier;
	private int compteur;
	private int numero;
	private float vieAvant = -1;

	@Override
	public void onInitializeClient() {
		fichier = FabricLoader.getInstance().getGameDir().resolve("compagnon").resolve("etat.json");
		ClientTickEvents.END_CLIENT_TICK.register(this::tick);
	}

	private void tick(Minecraft mc) {
		LocalPlayer joueur = mc.player;
		ClientLevel monde = mc.level;
		if (joueur == null || monde == null) {
			vieAvant = -1;
			return;
		}
		suivreDegats(joueur);
		if (++compteur % PERIODE_TICKS != 0) {
			return;
		}
		JsonObject etat = new JsonObject();
		etat.addProperty("version", 1);
		etat.addProperty("horodatage", System.currentTimeMillis());
		etat.add("joueur", decrireJoueur(joueur, monde));
		etat.add("monde", decrireMonde(monde));
		etat.add("vise", decrireCible(mc, monde));
		Screen ecran = mc.gui.screen(); // depuis 26.2, l'écran ouvert est rangé dans Gui
		etat.addProperty("menu", ecran == null ? (String) null : ecran.getClass().getSimpleName());
		etat.addProperty("pause", mc.isPaused());
		etat.add("monstres", decrireMonstres(joueur, monde));
		JsonArray liste = new JsonArray();
		evenements.forEach(liste::add);
		etat.add("evenements", liste);
		String json = gson.toJson(etat);
		ecrivain.execute(() -> ecrire(json));
	}

	private void suivreDegats(LocalPlayer joueur) {
		float vie = joueur.getHealth();
		if (vieAvant >= 0 && vie < vieAvant - 0.01f) {
			JsonObject e = new JsonObject();
			e.addProperty("n", ++numero);
			e.addProperty("type", "degats");
			e.addProperty("montant", vieAvant - vie);
			e.addProperty("cause", causeDegats(joueur));
			evenements.addLast(e);
			while (evenements.size() > EVENEMENTS_MAX) {
				evenements.removeFirst();
			}
		}
		vieAvant = vie;
	}

	private static String causeDegats(LocalPlayer joueur) {
		try {
			DamageSource source = joueur.getLastDamageSource();
			if (source == null) {
				return null;
			}
			Entity auteur = source.getEntity();
			return auteur != null ? auteur.getName().getString() : source.getMsgId();
		} catch (RuntimeException e) {
			return null;
		}
	}

	private static JsonObject decrireJoueur(LocalPlayer joueur, ClientLevel monde) {
		JsonObject j = new JsonObject();
		j.addProperty("nom", joueur.getName().getString());
		j.addProperty("vie", joueur.getHealth());
		j.addProperty("vie_max", joueur.getMaxHealth());
		j.addProperty("faim", joueur.getFoodData().getFoodLevel());
		j.addProperty("saturation", joueur.getFoodData().getSaturationLevel());
		j.addProperty("armure", joueur.getArmorValue());
		j.addProperty("niveau", joueur.experienceLevel);
		j.addProperty("air", joueur.getAirSupply());
		j.addProperty("air_max", joueur.getMaxAirSupply());
		j.addProperty("en_feu", joueur.isOnFire());
		j.addProperty("sous_eau", joueur.isUnderWater());
		j.addProperty("x", Math.round(joueur.getX() * 10) / 10.0);
		j.addProperty("y", Math.round(joueur.getY() * 10) / 10.0);
		j.addProperty("z", Math.round(joueur.getZ() * 10) / 10.0);
		j.addProperty("dimension", String.valueOf(monde.dimension()));
		BlockPos position = joueur.blockPosition();
		j.addProperty("biome", nomBiome(String.valueOf(monde.getBiome(position).unwrapKey().orElse(null))));
		j.addProperty("lumiere", monde.getMaxLocalRawBrightness(position));
		j.add("main", decrireObjet(joueur.getMainHandItem()));
		j.add("main_secondaire", decrireObjet(joueur.getOffhandItem()));
		JsonArray effets = new JsonArray();
		for (MobEffectInstance effet : joueur.getActiveEffects()) {
			effets.add(effet.getEffect().value().getDisplayName().getString());
		}
		j.add("effets", effets);
		return j;
	}

	/** « ResourceKey[minecraft:worldgen/biome / minecraft:birch_forest] » -> nom traduit (« Forêt de bouleaux »). */
	private static String nomBiome(String cle) {
		Matcher m = IDENTIFIANT.matcher(cle);
		String espace = null;
		String chemin = null;
		while (m.find()) {
			espace = m.group(1);
			chemin = m.group(2);
		}
		if (chemin == null) {
			return null;
		}
		return Component.translatable("biome." + espace + "." + chemin).getString();
	}

	private static JsonObject decrireObjet(ItemStack objet) {
		JsonObject o = new JsonObject();
		if (objet.isEmpty()) {
			o.addProperty("nom", (String) null);
			return o;
		}
		o.addProperty("nom", objet.getHoverName().getString());
		o.addProperty("nombre", objet.getCount());
		if (objet.isDamageableItem() && objet.getMaxDamage() > 0) {
			o.addProperty("usure", (double) objet.getDamageValue() / objet.getMaxDamage());
		}
		return o;
	}

	private static JsonObject decrireMonde(ClientLevel monde) {
		JsonObject m = new JsonObject();
		long temps = monde.getOverworldClockTime(); // depuis 26.1, le temps vient de l'horloge de la Surface
		m.addProperty("heure", temps % 24000L);
		m.addProperty("jour", temps / 24000L);
		m.addProperty("pluie", monde.isRaining());
		m.addProperty("orage", monde.isThundering());
		return m;
	}

	private static JsonObject decrireCible(Minecraft mc, ClientLevel monde) {
		JsonObject v = new JsonObject();
		HitResult cible = mc.hitResult;
		if (cible == null || cible.getType() == HitResult.Type.MISS) {
			return v;
		}
		if (cible instanceof BlockHitResult bloc) {
			v.addProperty("type", "bloc");
			v.addProperty("nom", monde.getBlockState(bloc.getBlockPos()).getBlock().getName().getString());
		} else if (cible instanceof EntityHitResult entite) {
			v.addProperty("type", "entite");
			v.addProperty("nom", entite.getEntity().getName().getString());
		}
		return v;
	}

	private static JsonArray decrireMonstres(LocalPlayer joueur, ClientLevel monde) {
		List<Entity> trouves = new ArrayList<>(monde.getEntities(joueur,
				joueur.getBoundingBox().inflate(RAYON_MONSTRES), e -> e instanceof Enemy && e.isAlive()));
		trouves.sort(Comparator.comparingDouble(joueur::distanceTo));
		JsonArray liste = new JsonArray();
		for (Entity e : trouves.subList(0, Math.min(8, trouves.size()))) {
			JsonObject m = new JsonObject();
			m.addProperty("nom", e.getName().getString());
			m.addProperty("id", String.valueOf(EntityType.getKey(e.getType())));
			m.addProperty("distance", Math.round(joueur.distanceTo(e) * 10) / 10.0);
			m.addProperty("direction", direction(joueur, e));
			double dy = e.getY() - joueur.getY();
			m.addProperty("hauteur", dy > 3 ? "au-dessus" : dy < -3 ? "en dessous" : "même niveau");
			liste.add(m);
		}
		return liste;
	}

	/** Position d'une entité par rapport au regard du joueur : devant, derrière, à gauche, à droite. */
	private static String direction(LocalPlayer joueur, Entity e) {
		double dx = e.getX() - joueur.getX();
		double dz = e.getZ() - joueur.getZ();
		double angleCible = Math.toDegrees(Math.atan2(-dx, dz)); // même repère que le lacet de Minecraft
		double ecart = ((angleCible - joueur.getYRot()) % 360 + 540) % 360 - 180; // entre -180 et 180
		if (Math.abs(ecart) <= 45) {
			return "devant";
		}
		if (Math.abs(ecart) >= 135) {
			return "derrière";
		}
		return ecart > 0 ? "à droite" : "à gauche";
	}

	private void ecrire(String json) {
		try {
			Files.createDirectories(fichier.getParent());
			Path temporaire = fichier.resolveSibling("etat.json.tmp");
			Files.writeString(temporaire, json, StandardCharsets.UTF_8);
			try {
				Files.move(temporaire, fichier, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
			} catch (IOException e) {
				// Windows refuse parfois le remplacement si le fichier est lu au même instant : écriture directe.
				Files.writeString(fichier, json, StandardCharsets.UTF_8);
			}
		} catch (IOException e) {
			// Rien de grave : la prochaine écriture aura lieu dans une demi-seconde.
		}
	}
}
