# minqlx - A Quake Live server administrator bot.
# Copyright (C) 2015 Mino <mino@minomino.org>

# This file is part of minqlxtended.

# minqlx is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# minqlx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with minqlxtended. If not, see <http://www.gnu.org/licenses/>.

"""Entity loader plugin for minqlxtended.

Manages .ent files that replace map entities at the engine level.

Place your .ent file in fs_homepath/baseq3/maps/ with the same name as the map
(e.g., dividedcrossings.ent for dividedcrossings map).

The .ent file replaces ALL entities in the map, including:
- Spawn points, teleporters, race checkpoints
- Items, weapons, armor, health
- Flags, targets, and all other entities

On Quake Live servers, .ent files must be packaged in .pk3 files to work.
The engine loads .pk3 files at startup and reads .ent files from them.

Commands:
    !eload - Verify .ent file exists and show what it contains
    !elist - List available .ent files
    !einfo <mapname> - Show entity count in a .ent file
    !epk3 - Package the .ent file into a .pk3 and reload the map
    !edebug - Show debugging info about .ent file status

Cvars:
    qlx_entAutoRestart: Automatically restart map when .ent file detected (default: 0)
"""

import minqlxtended
import os
import re
import zipfile
from typing import Dict, List, Optional


class entloader(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()
        
        # Set default cvars
        self.set_cvar_once("qlx_entAutoRestart", "0")
        
        # Add commands (using 'e' prefix since 'ent' prefix seems blocked)
        self.add_command("eload", self.cmd_entload, 2)
        self.add_command("elist", self.cmd_entlist, 1)
        self.add_command("einfo", self.cmd_entinfo, 1, usage="<mapname>")
        self.add_command("epk3", self.cmd_create_pk3, 3)
        self.add_command("edebug", self.cmd_debug, 2)
        
        # Add hooks
        self.add_hook("map", self.handle_map_change)
    
    def get_ent_directory(self) -> str:
        """Get the entity files directory path.
        
        Must be fs_homepath/baseq3/maps/ for the engine to load .ent files.
        """
        try:
            fs_homepath = minqlxtended.get_cvar("fs_homepath")
            if fs_homepath:
                return os.path.join(fs_homepath, "baseq3", "maps")
        except Exception:
            pass
        
        # Fallback - should rarely be used
        return "/home/qlserver/.quakelive/baseq3/maps"
    
    def parse_entities(self, content: str) -> List[Dict[str, str]]:
        """Parse entity definitions from .ent file content.
        
        Expected format is Quake entity format:
        {
        "key1" "value1"
        "key2" "value2"
        }
        {
        "key3" "value3"
        ...
        }
        """
        entities = []
        # Remove comments (lines starting with //)
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        
        # Split by opening braces to find entities
        entity_blocks = re.findall(r'\{([^}]*)\}', content, re.DOTALL)
        
        for block in entity_blocks:
            entity = {}
            # Find all key-value pairs
            # Pattern: "key" "value"
            pairs = re.findall(r'"([^"]*)"[^"]*"([^"]*)"', block)
            for key, value in pairs:
                entity[key.strip()] = value.strip()
            
            if entity:  # Only add non-empty entities
                entities.append(entity)
        
        return entities
    
    def load_ent_file(self, filename: str) -> Optional[List[Dict[str, str]]]:
        """Load and parse a .ent file.
        
        Args:
            filename: Name of the .ent file (with or without .ent extension)
        
        Returns:
            List of entity dictionaries, or None if file not found
        """
        ent_dir = self.get_ent_directory()
        
        # Add .ent extension if not present
        if not filename.endswith('.ent'):
            filename += '.ent'
        
        filepath = os.path.join(ent_dir, filename)
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            entities = self.parse_entities(content)
            return entities
        except FileNotFoundError:
            return None
        except Exception as e:
            raise Exception(f"Error loading file {filepath}: {str(e)}")
    
    def list_ent_files(self) -> List[str]:
        """List all available .ent files in the entity directory."""
        ent_dir = self.get_ent_directory()
        
        if not os.path.exists(ent_dir):
            raise FileNotFoundError(f"Entity directory does not exist: {ent_dir}")
        
        try:
            files = [f for f in os.listdir(ent_dir) if f.endswith('.ent')]
            return sorted(files)
        except Exception as e:
            raise Exception(f"Error listing files in {ent_dir}: {str(e)}")
    
    def get_entity_summary(self, entities: List[Dict[str, str]]) -> Dict[str, int]:
        """Get a summary count of entity types."""
        entity_types = {}
        for entity in entities:
            classname = entity.get('classname', 'unknown')
            entity_types[classname] = entity_types.get(classname, 0) + 1
        return entity_types
    
    def handle_map_change(self, mapname, factory):
        """Hook called when map changes. Check if .ent file exists."""
        try:
            current_map = minqlxtended.get_cvar("mapname")
            if not current_map:
                return
            
            entities = self.load_ent_file(current_map)
            if entities:
                entity_types = self.get_entity_summary(entities)
                self.msg(f"^3Detected '{current_map}.ent' with {len(entities)} entities.")
                # Show top 3 entity types
                top_types = sorted(entity_types.items(), key=lambda x: x[1], reverse=True)[:3]
                types_str = ', '.join([f"{name}({count})" for name, count in top_types])
                self.msg(f"^3Entity types: ^7{types_str}")
        except Exception:
            pass
    
    def cmd_entload(self, player, msg, channel):
        """Verify .ent file exists and show what it contains."""
        try:
            # Get current map name
            current_map = minqlxtended.get_cvar("mapname")
            if not current_map:
                channel.reply("^1Error: Could not determine current map.")
                return
            
            # Check if .ent file exists for current map
            entities = self.load_ent_file(current_map)
            if entities is None:
                channel.reply(f"^1No .ent file found for map '^7{current_map}^1'.")
                ent_dir = self.get_ent_directory()
                channel.reply(f"^3Place '{current_map}.ent' in: ^7{ent_dir}")
                return
            
            # Show entity summary
            entity_types = self.get_entity_summary(entities)
            channel.reply(f"^2Found '^7{current_map}.ent^2' with ^7{len(entities)}^2 entities:")
            
            # Show all entity types
            for ent_type, count in sorted(entity_types.items()):
                channel.reply(f"  ^7{ent_type}^2: {count}")
            
            channel.reply(f"^3The .ent file must be packaged in a .pk3 to work!")
            channel.reply(f"^3Use ^7!epk3^3 to create the .pk3 file automatically.")
            
        except Exception as e:
            channel.reply(f"^1Exception: {str(e)}")
    
    def cmd_entlist(self, player, msg, channel):
        """List all available .ent files."""
        try:
            files = self.list_ent_files()
            
            if not files:
                channel.reply("^1No .ent files found in the entity directory.")
                ent_dir = self.get_ent_directory()
                channel.reply(f"^3Directory: ^7{ent_dir}")
                return
            
            file_list = ", ".join([f[:-4] for f in files])  # Remove .ent extension for display
            channel.reply(f"^2Available entity files: ^7{file_list}")
        except Exception as e:
            channel.reply(f"^1Exception: {str(e)}")
    
    def cmd_entinfo(self, player, msg, channel):
        """Show information about a .ent file."""
        try:
            if len(msg) < 2:
                return minqlxtended.Return.USAGE
            
            filename = msg[1]
            entities = self.load_ent_file(filename)
            
            if entities is None:
                channel.reply(f"^1Error: Could not load entity file '^7{filename}^1'.")
                return
            
            entity_types = self.get_entity_summary(entities)
            
            channel.reply(f"^2File '^7{filename}^2' contains ^7{len(entities)}^2 entities:")
            for ent_type, count in sorted(entity_types.items()):
                channel.reply(f"  ^7{ent_type}^2: {count}")
        except Exception as e:
            channel.reply(f"^1Exception: {str(e)}")
    
    def cmd_create_pk3(self, player, msg, channel):
        """Package the current map's .ent file into a .pk3 for Quake Live to load."""
        try:
            current_map = minqlxtended.get_cvar("mapname")
            if not current_map:
                channel.reply("^1Error: Could not determine current map.")
                return
            
            # Check if .ent file exists
            entities = self.load_ent_file(current_map)
            if entities is None:
                channel.reply(f"^1No .ent file found for map '^7{current_map}^1'.")
                return
            
            ent_dir = self.get_ent_directory()
            ent_file = os.path.join(ent_dir, f"{current_map}.ent")
            
            # Get fs_homepath to put pk3 in baseq3 directory
            fs_homepath = minqlxtended.get_cvar("fs_homepath")
            pk3_dir = os.path.join(fs_homepath, "baseq3")
            pk3_name = f"zzz_{current_map}_entities.pk3"
            pk3_path = os.path.join(pk3_dir, pk3_name)
            
            channel.reply(f"^3Creating .pk3 file...")
            channel.reply(f"^2Source: ^7{ent_file}")
            channel.reply(f"^2Target: ^7{pk3_path}")
            
            # Create pk3 (which is just a zip file)
            try:
                # Remove old pk3 if it exists
                if os.path.exists(pk3_path):
                    os.remove(pk3_path)
                
                with zipfile.ZipFile(pk3_path, 'w', zipfile.ZIP_DEFLATED) as pk3:
                    # Add .ent file in the maps/ directory structure
                    pk3.write(ent_file, f"maps/{current_map}.ent")
                
                file_size = os.path.getsize(pk3_path)
                channel.reply(f"^2Successfully created ^7{pk3_name}^2 ({file_size} bytes)")
                channel.reply(f"^3The .pk3 contains {len(entities)} custom entities.")
                channel.reply(f"^2Restart the map with ^7/map {current_map}^2 to load the entities.")
                
            except Exception as e:
                channel.reply(f"^1Error creating .pk3 file: {str(e)}")
                return
        
        except Exception as e:
            channel.reply(f"^1Exception: {str(e)}")
    
    def cmd_debug(self, player, msg, channel):
        """Debug command to check .ent file status and server configuration."""
        try:
            current_map = minqlxtended.get_cvar("mapname")
            ent_dir = self.get_ent_directory()
            
            channel.reply(f"^3=== Entity File Debug Info ===")
            channel.reply(f"^2Current map: ^7{current_map}")
            channel.reply(f"^2Entity directory: ^7{ent_dir}")
            channel.reply(f"^2Directory exists: ^7{os.path.exists(ent_dir)}")
            
            # Check for .ent file
            ent_file = os.path.join(ent_dir, f"{current_map}.ent")
            channel.reply(f"^2.ent file path: ^7{ent_file}")
            channel.reply(f"^2.ent file exists: ^7{os.path.exists(ent_file)}")
            
            if os.path.exists(ent_file):
                size = os.path.getsize(ent_file)
                import stat
                perms = oct(os.stat(ent_file).st_mode)[-3:]
                channel.reply(f"^2File size: ^7{size} bytes")
                channel.reply(f"^2File permissions: ^7{perms}")
                
                # Read first entity
                entities = self.load_ent_file(current_map)
                if entities and len(entities) > 0:
                    first_ent = entities[0]
                    channel.reply(f"^2First entity classname: ^7{first_ent.get('classname', 'unknown')}")
            
            # Check for .bsp file
            bsp_file = os.path.join(ent_dir, f"{current_map}.bsp")
            channel.reply(f"^2.bsp file exists: ^7{os.path.exists(bsp_file)}")
            
            # Check relevant cvars
            try:
                fs_game = minqlxtended.get_cvar("fs_game")
                channel.reply(f"^2fs_game: ^7{fs_game}")
            except:
                pass
            
            try:
                fs_homepath = minqlxtended.get_cvar("fs_homepath")
                channel.reply(f"^2fs_homepath: ^7{fs_homepath}")
            except:
                pass
            
            channel.reply(f"^3=========================")
            channel.reply(f"^1To load .ent files on servers:")
            channel.reply(f"^2Package the .ent file in a .pk3")
            channel.reply(f"^3Use ^7!epk3^3 to create the .pk3 automatically.")
            
        except Exception as e:
            channel.reply(f"^1Exception: {str(e)}")
